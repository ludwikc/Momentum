import asyncio
import json
import logging
import os
import re
import secrets
import unicodedata
from datetime import datetime

import discord
import pytz
from discord import app_commands
from discord.ext import commands, tasks
from discord.ext import voice_recv

import dave_patch
import ssrc_patch
import gdrive
import transcribe
import transcripts
from parsers import parse_recording_filename
from mixsink import MixingWaveSink
from taskutil import cancel_unless_current
from config import (
    RECORDING_NOTIFY_CHANNEL_ID,
    RECORDING_MAX_MINUTES,
    AUTO_RECORD_ENABLED,
    AUTO_RECORD_CHANNEL_IDS,
    AUTO_RECORD_MIN_MEMBERS,
    START_SOUND_CHANNEL_IDS,
    RECORDING_THANKYOU_VOICE_CHANNEL_IDS,
    RECORDING_THANKYOU_CHANNEL_ID,
    RECORDING_SUMMARY_CHANNEL_ID,
    RECORDING_MIN_PARTICIPANTS,
    DIARIZATION_ENABLED,
)

# Add DAVE (E2EE) decryption support to voice_recv — without this, Discord's
# mandatory end-to-end encryption makes every recording silent ("corrupted stream").
dave_patch.apply()
# Fix a voice_recv crash that leaves a dead voice client stuck in "recording"
# state forever, silently blocking all future auto-record joins.
ssrc_patch.apply()

logger = logging.getLogger("momentum_bot.voicerecord")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
SOUND_DIR = os.path.join(BASE_DIR, "data")


def _find_start_sound() -> str | None:
    """Return the 'now recording' sound file (data/now_recording.*), if present."""
    import glob
    matches = sorted(glob.glob(os.path.join(SOUND_DIR, "now_recording.*")))
    return matches[0] if matches else None

GREEN = 0x2ecc71
GREY = 0x95a5a6
RED = 0xe74c3c


def slug_channel_name(name: str) -> str:
    """Turn a Discord channel name into a filename-safe slug.

    Drops the leading "<emoji><spacer>" prefix (all leading non-alphanumeric
    characters) and slugifies the rest: Polish diacritics -> ASCII, lowercased,
    runs of non [a-z0-9] collapsed to single hyphens.
        '🔢│1234-daily-coaching'    -> '1234-daily-coaching'
        '🎭   Warsztaty Lifehackerów' -> 'warsztaty-lifehackerow'
    """
    # Strip leading emoji / separators / whitespace until the real name starts.
    i = 0
    while i < len(name) and not name[i].isalnum():
        i += 1
    name = name[i:]
    # 'ł' has no NFKD decomposition, so transliterate it explicitly.
    name = name.replace("ł", "l").replace("Ł", "L")
    # Decompose remaining diacritics (ó, ą, ę, ć, ń, ś, ź, ż, …) and drop the marks.
    name = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    name = re.sub(r"[^a-z0-9]+", "-", name.lower())
    return name.strip("-") or "channel"


class RecordingPanel(discord.ui.View):
    """Ephemeral control panel shown while recording: a Stop button."""

    def __init__(self, cog: "VoiceRecord", timeout: float):
        super().__init__(timeout=timeout)
        self.cog = cog

    @discord.ui.button(label="Zatrzymaj nagrywanie", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.recording:
            await interaction.response.send_message("⚠️ Nic teraz nie nagrywam.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.cog._finish_and_publish(suppress_auto=True)  # updates this panel to the "ended" state
        self.stop()


class VoiceRecord(commands.Cog):
    """Records a voice channel, mixes it to a single MP3 and uploads it to
    a Google Drive Shared Drive. On-demand via /nagraj (mod-only), plus
    presence-based auto-recording of watched channels (config.AUTO_RECORD_*)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.warsaw = pytz.timezone("Europe/Warsaw")

        # Active-recording state (one at a time).
        self.vc: voice_recv.VoiceRecvClient | None = None
        self.wav_path: str | None = None
        self.channel: discord.VoiceChannel | None = None
        self.start_time: datetime | None = None
        self.is_auto = False
        self.rec_id: str | None = None
        self.participants: list[int] = []  # user ids present during the recording (ordered)
        self._panel_msg: discord.WebhookMessage | None = None
        self._safety_task: asyncio.Task | None = None
        # Watched channels where a mod manually stopped recording while people were
        # still present — auto-record stays paused here until the channel empties
        # (a new call) or a mod runs /nagraj again.
        self._suppressed: set[int] = set()
        # Serializes start/stop so rapid voice-state events can't double-trigger.
        self._lock = asyncio.Lock()
        # One orphan-recovery pass per process (on_ready re-fires on reconnects).
        self._recovery_ran = False

        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        logger.info("VoiceRecord cog initialized")

    # ----------------------------------------------------------------- lifecycle
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.auto_sweep.is_running():
            self.auto_sweep.start()
        if not self._recovery_ran:
            self._recovery_ran = True
            asyncio.create_task(self._recover_orphans())
        logger.info("VoiceRecord cog is ready (auto-record: %s, channels: %s)",
                    AUTO_RECORD_ENABLED, AUTO_RECORD_CHANNEL_IDS)

    def cog_unload(self):
        if self.auto_sweep.is_running():
            self.auto_sweep.cancel()
        if self._safety_task:
            self._safety_task.cancel()
        if self.vc:
            # Best-effort: stop a recording in progress on reload.
            asyncio.create_task(self._teardown())

    # ----------------------------------------------------------------- recording
    @property
    def recording(self) -> bool:
        return self.vc is not None

    async def _start(self, channel: discord.VoiceChannel, *, auto: bool = False) -> str:
        """Connect and begin capturing. Returns the wav path. Raises on failure."""
        if self.recording:
            raise RuntimeError("Nagrywanie już trwa.")

        vc: voice_recv.VoiceRecvClient = await channel.connect(cls=voice_recv.VoiceRecvClient)

        rec_id = secrets.token_hex(3)  # short id shared by the panel and the filename
        ts = datetime.now(self.warsaw).strftime("%Y-%m-%d-%H-%M-%S")
        slug = slug_channel_name(channel.name)
        wav_path = os.path.join(RECORDINGS_DIR, f"Lifehackerzy_{ts}_{slug}_{rec_id}.wav")
        # MixingWaveSink sums every speaker onto one timeline and writes a single
        # WAV. The library's WaveSink/SilenceGeneratorSink combo would instead
        # concatenate per-speaker frames (N-speaker call -> ~N x too long) and let
        # two threads race on the non-thread-safe wave file (corrupt header). See
        # mixsink.py for the full story.
        sink = MixingWaveSink(wav_path)
        vc.listen(sink, after=self._on_listen_done)

        # Play the "now recording" announcement out loud — only on configured
        # channels. Does not affect the recording, which captures audio received
        # from other participants, not what the bot itself plays.
        if channel.id in START_SOUND_CHANNEL_IDS:
            sound = _find_start_sound()
            if sound:
                try:
                    vc.play(discord.FFmpegPCMAudio(sound))
                except Exception as e:
                    logger.warning("Failed to play start sound: %s", e)

        self.vc = vc
        self.wav_path = wav_path
        self.channel = channel
        self.start_time = datetime.now(self.warsaw)
        self.is_auto = auto
        self.rec_id = rec_id
        self.participants = [m.id for m in channel.members if not m.bot]
        # A deliberate (re-)start re-arms normal auto behavior for this channel.
        self._suppressed.discard(channel.id)
        self._safety_task = asyncio.create_task(self._safety_stop())
        logger.info("Recording started in #%s -> %s (auto=%s)", channel.name, wav_path, auto)
        return wav_path

    def _on_listen_done(self, exc: Exception | None):
        if exc:
            logger.error("Voice listener stopped with error: %s", exc)

    async def _safety_stop(self):
        """Auto-stop after the configured cap so a forgotten recording can't run forever."""
        try:
            await asyncio.sleep(RECORDING_MAX_MINUTES * 60)
        except asyncio.CancelledError:
            return
        if self.recording:
            logger.info("Safety cap reached (%s min) — stopping recording", RECORDING_MAX_MINUTES)
            # This task now runs the publish pipeline itself. Clear the handle
            # first so _teardown can't cancel the very task executing it —
            # that self-cancel silently killed every ≥cap recording's
            # transcript/upload before this guard existed.
            self._safety_task = None
            await self._finish_and_publish(reason="limit czasu")

    async def _teardown(self) -> str | None:
        """Stop listening, disconnect, and clear state. Returns the wav path."""
        wav_path = self.wav_path
        vc = self.vc
        if self._safety_task:
            cancel_unless_current(self._safety_task)
            self._safety_task = None
        if vc:
            try:
                vc.stop_listening()  # flushes & closes the wav file
            except Exception as e:
                logger.error("stop_listening failed: %s", e)
            await asyncio.sleep(0.5)
            try:
                await vc.disconnect(force=True)
            except Exception as e:
                logger.error("disconnect failed: %s", e)
        self.vc = None
        self.wav_path = None
        self.channel = None
        self.start_time = None
        self.is_auto = False
        self.rec_id = None
        self.participants = []
        return wav_path

    async def _transcode_to_mp3(self, wav_path: str) -> str | None:
        """WAV -> MP3 via ffmpeg. Returns mp3 path, or None on failure."""
        mp3_path = wav_path[:-4] + ".mp3" if wav_path.endswith(".wav") else wav_path + ".mp3"
        # -hide_banner drops the ~1.5 KB version/configuration preamble so the
        # captured stderr tail is the actual error, not the build banner (which
        # previously masked the real "Invalid data found" message in the logs).
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-y", "-i", wav_path,
            "-codec:a", "libmp3lame", "-qscale:a", "4", mp3_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("ffmpeg transcode failed (%s): %s", proc.returncode,
                         stderr.decode("utf-8", "replace")[-1000:])
            return None
        return mp3_path

    async def _recover_orphans(self):
        """Finish the publish pipeline for recordings that never got one.

        A crash/restart mid-recording (or the pre-fix safety-cap self-cancel)
        leaves a closed WAV with no transcript — the meeting silently vanishes
        from Momentum's memory. Run the missing transcode → transcribe → save →
        upload steps for each orphan, oldest first. Best-effort per file: one
        failure never blocks the next, and a failed WAV stays on disk for the
        next startup's retry.
        """
        try:
            rec_names = os.listdir(RECORDINGS_DIR)
        except OSError:
            return
        try:
            tr_names = os.listdir(transcripts.TRANSCRIPTS_DIR)
        except OSError:
            tr_names = []
        orphans = sorted(transcripts.find_orphans(rec_names, tr_names))
        if not orphans:
            return
        logger.info("Orphaned recordings to recover: %s", orphans)
        for fname in orphans:
            wav_path = os.path.join(RECORDINGS_DIR, fname)
            if wav_path == self.wav_path:
                continue  # an active recording is not an orphan
            parsed = parse_recording_filename(fname)
            if parsed is None:
                continue
            started, slug, rec_id = parsed
            try:
                await self._publish_recovered(wav_path, started, slug, rec_id)
            except Exception:
                logger.exception("Recovery failed for %s", fname)

    async def _publish_recovered(self, wav_path: str, started: datetime,
                                 channel_slug: str, rec_id: str):
        """Transcode/transcribe/save/upload one orphaned WAV (see _recover_orphans).

        Mirrors the live pipeline minus the parts that need live state: no
        thank-you, no summary post (participants unknown, meeting long past) —
        the goal is the transcript back in Momentum's memory and the audio on
        Drive. The WAV is deleted only once its content is safe (transcript
        saved, or transcription unconfigured), so a transient failure retries
        on the next startup.
        """
        mp3_path = await self._transcode_to_mp3(wav_path)
        if mp3_path is None:
            await self._notify(
                f"⚠️ Odzyskiwanie nagrania `{rec_id}` nie powiodło się "
                f"(transkodowanie) — plik zostaje: `{wav_path}`"
            )
            return
        transcript = None
        saved = False
        if transcribe.is_configured():
            # _build_transcript unconditionally consumes (deletes) the diarization
            # sidecar. Keep a copy so a failed save_transcript below can restore it
            # for the next startup's retry instead of losing speaker attribution.
            diar_path = wav_path + ".diarization.json"
            diar_content = None
            if os.path.exists(diar_path):
                try:
                    with open(diar_path, "r", encoding="utf-8") as f:
                        diar_content = f.read()
                except OSError:
                    diar_content = None
            try:
                text, words = await asyncio.to_thread(transcribe.transcribe_words, mp3_path)
                transcript = self._build_transcript(text, words, wav_path)
                if transcript:
                    saved = bool(await asyncio.to_thread(
                        transcripts.save_transcript, transcript,
                        started=started, channel_name=channel_slug, rec_id=rec_id,
                    ))
                if transcript and not saved and diar_content is not None:
                    try:
                        with open(diar_path, "w", encoding="utf-8") as f:
                            f.write(diar_content)
                    except OSError as e:
                        logger.warning(
                            "Failed to restore diarization sidecar for %s: %s", rec_id, e
                        )
            except Exception as e:
                logger.error("Recovery transcription failed for %s: %s", rec_id, e)
        terminal = saved or not transcribe.is_configured()
        if terminal:
            try:
                os.remove(wav_path)
            except OSError:
                pass
        else:
            # Transcription is configured but failed this time — the WAV stays
            # for the next startup's retry. Don't ship a Drive copy yet: every
            # retry would otherwise upload another duplicate (Drive doesn't
            # dedupe by name), so drop the intermediate mp3 and try again later.
            try:
                os.remove(mp3_path)
            except OSError:
                pass
            await self._notify(
                f"⚠️ Odzyskiwanie nagrania `{rec_id}` — transkrypcja się nie udała, "
                f"spróbuję ponownie przy następnym starcie (WAV zostaje)."
            )
            return
        msg = (f"♻️ Odzyskane nagranie z **#{channel_slug}** "
               f"({started.strftime('%Y-%m-%d %H:%M')})")
        if gdrive.is_configured():
            try:
                info = await asyncio.to_thread(
                    gdrive.upload_file, mp3_path, os.path.basename(mp3_path)
                )
                msg += f": {info.get('webViewLink')}"
                if transcript:
                    await self._upload_transcript(mp3_path, transcript)
                remote_md5 = info.get("md5Checksum")
                local_md5 = await asyncio.to_thread(gdrive.local_md5, mp3_path)
                if remote_md5 and remote_md5 == local_md5:
                    try:
                        os.remove(mp3_path)
                    except OSError:
                        pass
                else:
                    msg += (f"\n⚠️ Nie udało się zweryfikować kopii na Drive — "
                            f"lokalna kopia: `{mp3_path}`")
            except Exception as e:
                logger.error("Recovery Drive upload failed for %s: %s", rec_id, e)
                msg += f" — upload na Drive nie powiódł się, plik lokalnie: `{mp3_path}`"
        else:
            msg += f" — zapisane lokalnie: `{mp3_path}`"
        if saved:
            msg += "\n📝 Transkrypcja odzyskana — Momentum znów pamięta to spotkanie."
        await self._notify(msg)

    async def _finish_and_publish(self, reason: str | None = None, *, suppress_auto: bool = False) -> str:
        """Stop the recording, transcode, upload (or keep local), notify. Returns a status message."""
        # Snapshot panel/participant data before teardown clears the recording state.
        channel, started, rec_id = self.channel, self.start_time, self.rec_id
        # A manual stop while the call is still populated must not be undone by the
        # auto-record sweep: pause auto-record for this channel until it empties.
        if (suppress_auto and channel is not None
                and channel.id in AUTO_RECORD_CHANNEL_IDS
                and self._humans(channel) >= AUTO_RECORD_MIN_MEMBERS):
            self._suppressed.add(channel.id)
        participants = list(self.participants)
        # The thank-you and summary are only worth posting for an actual group
        # call — skip both when fewer than RECORDING_MIN_PARTICIPANTS took part.
        enough_participants = len(participants) >= RECORDING_MIN_PARTICIPANTS
        panel, self._panel_msg = self._panel_msg, None
        channel_name = channel.name if channel else "?"
        link: str | None = None

        wav_path = await self._teardown()
        if not wav_path or not os.path.exists(wav_path):
            msg = "Nie udało się zapisać nagrania (brak pliku audio)."
        else:
            mp3_path = await self._transcode_to_mp3(wav_path)
            if mp3_path is None:
                msg = f"Nagranie zapisane, ale konwersja do MP3 nie powiodła się. Plik WAV: `{wav_path}`"
            else:
                try:
                    os.remove(wav_path)  # WAV no longer needed once the MP3 exists
                except OSError:
                    pass

                # Transcribe + summarize from the MP3 (best-effort; never blocks
                # publishing the recording). Done before any upload so the local
                # MP3 is still on disk.
                transcript = summary = None
                if transcribe.is_configured():
                    try:
                        text, words = await asyncio.to_thread(
                            transcribe.transcribe_words, mp3_path
                        )
                        transcript = self._build_transcript(text, words, wav_path)
                        if transcript:
                            # Keep a local copy so Momentum can recall the meeting
                            # later (transcripts/ is gitignored). Best-effort.
                            if started is not None and rec_id is not None:
                                await asyncio.to_thread(
                                    transcripts.save_transcript, transcript,
                                    started=started, channel_name=channel_name, rec_id=rec_id,
                                )
                            summary = await asyncio.to_thread(
                                transcribe.summarize, transcript, channel_name
                            )
                    except Exception as e:
                        logger.error("Transcription/summary failed: %s", e)

                suffix = f" ({reason})" if reason else ""
                if gdrive.is_configured():
                    try:
                        info = await asyncio.to_thread(
                            gdrive.upload_file, mp3_path, os.path.basename(mp3_path)
                        )
                        link = info.get("webViewLink")
                        msg = f"🎙️ Nagranie z **#{channel_name}**{suffix} gotowe: {link}"
                        # Store the transcript next to the audio (best-effort).
                        if transcript:
                            await self._upload_transcript(mp3_path, transcript)
                        # Only delete the single local copy once the Drive copy is
                        # verified byte-for-byte (local MD5 == Drive's md5Checksum).
                        # On any mismatch/missing hash, keep the local file so a
                        # corrupted upload can never lose the recording.
                        remote_md5 = info.get("md5Checksum")
                        local_md5 = await asyncio.to_thread(gdrive.local_md5, mp3_path)
                        if remote_md5 and remote_md5 == local_md5:
                            try:
                                os.remove(mp3_path)
                                logger.info("Local recording deleted after verified "
                                            "upload (md5=%s): %s", local_md5, mp3_path)
                            except OSError as e:
                                logger.warning("Verified upload but local delete failed "
                                               "for %s: %s", mp3_path, e)
                        else:
                            logger.error("Drive upload hash mismatch for %s "
                                         "(local=%s remote=%s) — keeping local copy",
                                         mp3_path, local_md5, remote_md5)
                            msg += ("\n⚠️ Nie udało się zweryfikować integralności kopii "
                                    f"na Drive — lokalna kopia zachowana: `{mp3_path}`")
                    except Exception as e:
                        logger.error("Drive upload failed: %s", e)
                        msg = (f"🎙️ Nagranie z **#{channel_name}**{suffix} zapisane lokalnie "
                               f"(upload na Drive nie powiódł się: {e}). Plik: `{mp3_path}`")
                else:
                    msg = (f"🎙️ Nagranie z **#{channel_name}**{suffix} zapisane lokalnie: `{mp3_path}`\n"
                           f"_(Google Drive nie jest skonfigurowany — ustaw GDRIVE_SA_JSON i GDRIVE_FOLDER_ID.)_")

                # Post the AI summary (only for a real group call), regardless of
                # where the audio ended up.
                if summary and enough_participants:
                    await self._post_summary(channel, started, summary)

        await self._notify(msg)

        # Update the ephemeral panel to the "ended" state (best-effort).
        if panel is not None:
            try:
                ended = self._panel_embed(channel, started, rec_id, state="ended", status=msg, link=link)
                await panel.edit(embed=ended, view=None)
            except Exception as e:
                logger.debug("Panel update on stop failed: %s", e)

        # Thank the participants in the announce channel (configured channels only,
        # and only for a real group call).
        if (channel is not None and channel.id in RECORDING_THANKYOU_VOICE_CHANNEL_IDS
                and enough_participants):
            await self._post_thankyou(participants)

        return msg

    async def _post_thankyou(self, participants: list[int]):
        if not participants:
            return
        channel = self.bot.get_channel(RECORDING_THANKYOU_CHANNEL_ID)
        if channel is None:
            logger.error("Thank-you channel %s not found", RECORDING_THANKYOU_CHANNEL_ID)
            return
        mentions = ", ".join(f"<@{uid}>" for uid in participants)
        try:
            await channel.send(
                f"{mentions} - dzięki za dzisiejsze rozkminki!",
                allowed_mentions=discord.AllowedMentions(users=True),
            )
            logger.info("Posted thank-you for %d participant(s)", len(participants))
        except Exception as e:
            logger.error("Failed to post thank-you: %s", e)

    def _build_transcript(self, text: str, words: list[dict], wav_path: str) -> str:
        """Speaker-label the transcript using the sink's diarization sidecar.

        The MixingWaveSink wrote `<wav>.diarization.json` (ground-truth speaking
        timeline) next to the recording; we attribute each transcribed word to the
        speaker active at that time. Falls back to the plain transcript if
        diarization is disabled, the sidecar is missing, or anything goes wrong.
        Consumes (deletes) the sidecar either way.
        """
        diar_path = wav_path + ".diarization.json"
        if not (DIARIZATION_ENABLED and text and words and os.path.exists(diar_path)):
            return text
        try:
            with open(diar_path, "r", encoding="utf-8") as f:
                segments = json.load(f).get("segments") or []
            labeled = transcribe.diarize(words, segments)
            return labeled or text
        except Exception as e:
            logger.error("Diarization failed, using plain transcript: %s", e)
            return text
        finally:
            try:
                os.remove(diar_path)
            except OSError:
                pass

    async def _upload_transcript(self, mp3_path: str, transcript: str):
        """Write the transcript to a .txt next to the audio and upload it to Drive."""
        txt_path = (mp3_path[:-4] if mp3_path.endswith(".mp3") else mp3_path) + ".txt"
        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(transcript)
            await asyncio.to_thread(
                gdrive.upload_file, txt_path, os.path.basename(txt_path), "text/plain"
            )
        except Exception as e:
            logger.warning("Transcript upload failed: %s", e)
        finally:
            try:
                os.remove(txt_path)
            except OSError:
                pass

    async def _post_summary(self, rec_channel, started_at, summary: str):
        """Post the AI-generated summary to the configured summary channel.

        The header references the recorded voice channel (as a clickable mention)
        and the recording date. The Google Drive link is deliberately NOT included
        here — that link goes only to the mod-only notify channel.
        """
        target = self.bot.get_channel(RECORDING_SUMMARY_CHANNEL_ID)
        if target is None:
            logger.error("Summary channel %s not found", RECORDING_SUMMARY_CHANNEL_ID)
            return
        # Channel mentions render in embed descriptions (but not in embed titles),
        # so the header lives at the top of the description.
        date = f"<t:{int(started_at.timestamp())}:D>" if started_at is not None else ""
        chan_ref = rec_channel.mention if rec_channel is not None else "kanału głosowego"
        header = f"{chan_ref} z dn. {date}".strip()
        description = f"**{header}**\n\n{summary}"
        embed = discord.Embed(description=description[:4096], color=GREEN)  # 4096 char cap
        try:
            await target.send(embed=embed)
            logger.info("Posted recording summary for %s", header)
        except Exception as e:
            logger.error("Failed to post summary: %s", e)

    def _panel_embed(self, channel, started_at, rec_id, *,
                     state: str = "recording", status: str | None = None,
                     link: str | None = None) -> discord.Embed:
        """Build the recording control-panel embed (Craig-style box)."""
        if state == "recording":
            embed = discord.Embed(title="🔴 Nagrywanie...", color=GREEN)
            embed.set_footer(text="Nagranie trafi na Google Drive po zatrzymaniu • E2EE/DAVE")
        else:
            embed = discord.Embed(title="⏹️ Nagranie zakończone", color=GREY)
        if channel is not None:
            embed.add_field(name="Kanał", value=channel.mention, inline=True)
        if started_at is not None:
            ts = int(started_at.timestamp())
            embed.add_field(name="Rozpoczęto", value=f"<t:{ts}:T> (<t:{ts}:R>)", inline=True)
        if rec_id:
            embed.add_field(name="ID nagrania", value=f"`{rec_id}`", inline=True)
        if link:
            embed.add_field(name="Plik", value=f"[Otwórz na Google Drive]({link})", inline=False)
        elif state != "recording" and status:
            embed.add_field(name="Status", value=status, inline=False)
        return embed

    async def _notify(self, message: str):
        channel = self.bot.get_channel(RECORDING_NOTIFY_CHANNEL_ID)
        if channel:
            try:
                await channel.send(message)
            except Exception as e:
                logger.error("Failed to post to notify channel: %s", e)

    # ----------------------------------------------------------------- commands
    @app_commands.command(name="nagraj", description="Rozpocznij nagrywanie kanału głosowego")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def nagraj(self, interaction: discord.Interaction):
        if self.recording:
            await interaction.response.send_message(
                f"⚠️ Nagrywanie już trwa na **#{self.channel.name}**.", ephemeral=True
            )
            return

        voice = getattr(interaction.user, "voice", None)
        if not voice or not voice.channel:
            await interaction.response.send_message(
                "⚠️ Najpierw dołącz do kanału głosowego, potem użyj `/nagraj`.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await self._start(voice.channel)
        except Exception as e:
            logger.error("Failed to start recording: %s", e)
            await interaction.followup.send(f"❌ Nie udało się rozpocząć nagrywania: {e}", ephemeral=True)
            return
        view = RecordingPanel(self, timeout=RECORDING_MAX_MINUTES * 60)
        embed = self._panel_embed(self.channel, self.start_time, self.rec_id, state="recording")
        self._panel_msg = await interaction.followup.send(
            embed=embed, view=view, ephemeral=True, wait=True
        )

    @app_commands.command(name="stop_nagrywania", description="Zatrzymaj nagrywanie i wyślij plik")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def stop_nagrywania(self, interaction: discord.Interaction):
        if not self.recording:
            await interaction.response.send_message("⚠️ Nic teraz nie nagrywam.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        msg = await self._finish_and_publish(suppress_auto=True)
        await interaction.followup.send(f"⏹️ Zatrzymano. {msg}", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            text = "⛔ Tej komendy mogą używać tylko moderatorzy."
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        else:
            logger.error("voicerecord command error: %s", error)

    # ----------------------------------------------------------------- auto-record
    @staticmethod
    def _humans(channel: discord.VoiceChannel | None) -> int:
        return len([m for m in channel.members if not m.bot]) if channel else 0

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Track participants of an active recording, and start/stop auto-recording."""
        if member.bot:
            return
        # Accumulate anyone who is in the channel currently being recorded.
        if (self.recording and self.channel is not None
                and after.channel is not None and after.channel.id == self.channel.id
                and member.id not in self.participants):
            self.participants.append(member.id)

        if not AUTO_RECORD_ENABLED:
            return
        # Only react when a watched channel was involved in this state change.
        touched = {c.id for c in (before.channel, after.channel) if c is not None}
        if not touched & set(AUTO_RECORD_CHANNEL_IDS):
            return
        await self._evaluate_auto()

    async def _evaluate_auto(self):
        """Start auto-recording the first eligible channel, or stop if ours emptied."""
        async with self._lock:
            # Defense in depth: if the voice client died without us noticing (a
            # crash in the discord.py/voice_recv internals, a dropped connection,
            # etc.), self.recording would stay stuck True forever and silently
            # block every future auto-record join. Detect and clear it.
            if self.vc is not None and not self.vc.is_connected():
                logger.warning(
                    "Voice client for #%s found disconnected while marked as "
                    "recording — clearing stuck state",
                    self.channel.name if self.channel else "?",
                )
                await self._teardown()

            # Stop: an auto recording whose channel dropped below the threshold.
            if self.recording and self.is_auto and self.channel is not None:
                if self._humans(self.channel) < AUTO_RECORD_MIN_MEMBERS:
                    await self._finish_and_publish(reason="poniżej 2 osób")
                return

            if self.recording:
                return  # manual (or already-running auto) recording in progress

            # Lift suppression once a manually-stopped channel has emptied: the call
            # ended, so the next call there should auto-record again.
            for cid in list(self._suppressed):
                ch = self.bot.get_channel(cid)
                if not isinstance(ch, discord.VoiceChannel) or self._humans(ch) < AUTO_RECORD_MIN_MEMBERS:
                    self._suppressed.discard(cid)

            # Start: first watched channel that has reached the member threshold.
            for cid in AUTO_RECORD_CHANNEL_IDS:
                if cid in self._suppressed:
                    continue  # manually stopped while populated — wait for it to empty
                channel = self.bot.get_channel(cid)
                if isinstance(channel, discord.VoiceChannel) and self._humans(channel) >= AUTO_RECORD_MIN_MEMBERS:
                    try:
                        await self._start(channel, auto=True)
                        await self._notify(
                            f"🔴 Automatyczne nagrywanie **#{channel.name}** rozpoczęte "
                            f"({self._humans(channel)} osób)."
                        )
                    except Exception as e:
                        logger.error("Auto-record failed to start in %s: %s", cid, e)
                    return

    @tasks.loop(seconds=60)
    async def auto_sweep(self):
        """Backstop in case a voice-state event was missed: re-evaluate periodically."""
        if AUTO_RECORD_ENABLED:
            await self._evaluate_auto()

    @auto_sweep.before_loop
    async def before_auto_sweep(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceRecord(bot))
