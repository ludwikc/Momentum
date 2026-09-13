"""Momentum mówi — live voice replies in the voice channel.

Somebody says "Momentum, co o tym myślisz?" during a recorded call and the bot
answers out loud, with the same brain, persona and tools as a text summon.

This cog deliberately owns **no voice connection**. It borrows the one
``cogs/voicerecord.py`` already holds (and its ``MixingWaveSink``), so the whole
feature is scoped to "while a recording is running" — which, thanks to
auto-record, means "while there is a real call happening". Nothing to connect,
nothing to disconnect, no second bot in the channel.

Pipeline per utterance:

    sink buffers PCM  →  poll (0.25 s)  →  gating  →  Whisper  →  window
                      →  wake word?     →  model   →  TTS      →  vc.play + mix

The VAD everybody else has to build is already done: Discord only sends packets
while a person speaks, and ``MixingWaveSink`` already coalesces those frames into
turns for diarization. ``take_finished_utterances`` just hands us the closed ones.
"""
import asyncio
import logging
import os
import tempfile
import time
from collections import deque
from datetime import datetime

import discord
import pytz
from discord.ext import commands, tasks

import transcribe
import tts
import voice_live
from cogs import przywolanie
from summon import DailyRateLimiter, build_summon_prompt
from config import (
    DIARIZATION_GAP_FRAMES,
    MOMENTUM_OWNER_ID,
    VOICE_LIVE_ALLOW_EVERYONE,
    VOICE_LIVE_BARGEIN_SECONDS,
    VOICE_LIVE_CONTEXT_FROM_ALL,
    VOICE_LIVE_CONTEXT_UTTERANCES,
    VOICE_LIVE_DAILY_LIMIT,
    VOICE_LIVE_ENABLED,
    VOICE_LIVE_TIMEOUT_S,
)

logger = logging.getLogger("momentum_bot.voice_live")

# Poll cadence. Cheap (a dict scan under a lock) and it bounds how long a
# finished utterance waits before we start working on it.
_POLL_SECONDS = 0.25
# An utterance is "finished" after the same silence gap diarization uses for a
# turn boundary, so live segmentation and the transcript agree on where one
# person's turn ended. 25 frames = 0.5 s.
_GAP_SECONDS = DIARIZATION_GAP_FRAMES * 0.02
# How stale sink.last_human_frame may be and still count as "talking right now".
_FRESH_SECONDS = 0.15
# No barge-in at all during the opening moment of a reply — see _wait_or_yield.
_BARGEIN_GRACE_SECONDS = 0.75


def _stop_playing(vc) -> None:
    """Stop the bot's playback WITHOUT stopping the recording.

    NEVER call ``vc.stop()`` here. ``VoiceRecvClient`` overrides it to stop
    playing *and* listening (voice_recv `voice_client.py:169`), so on 13.09.2026
    the first real barge-in tore down the recording sink 2 ms after the bot
    finished speaking: the call kept going, the bot stayed connected, and both the
    recording and every further reply were silently dead. ``stop_playing()`` is
    the one that only touches playback.
    """
    vc.stop_playing()


class TeeSource(discord.AudioSource):
    """Wraps an AudioSource, copying every frame to ``tee`` on the way out.

    Used to feed the bot's own speech back into the recording's mix — see
    ``MixingWaveSink.write_bot_frame`` for why that matters. A failure in the tee
    must never silence the bot, so it is swallowed (logged once).
    """

    def __init__(self, source: discord.AudioSource, tee):
        self._source = source
        self._tee = tee
        self._tee_failed = False

    def read(self) -> bytes:
        data = self._source.read()
        if data and not self._tee_failed:
            try:
                self._tee(data)
            except Exception:
                self._tee_failed = True
                logger.exception("Tee into the recording failed — bot audio will "
                                 "be missing from this transcript")
        return data

    def is_opus(self) -> bool:
        return self._source.is_opus()

    def cleanup(self) -> None:
        self._source.cleanup()


class VoiceLive(commands.Cog):
    """Answers out loud when called by name during a recorded call."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.warsaw = pytz.timezone("Europe/Warsaw")
        # Rolling transcript of the call, in build_summon_prompt's shape.
        self._window: deque[dict] = deque(maxlen=VOICE_LIVE_CONTEXT_UTTERANCES)
        self._limiter = DailyRateLimiter(VOICE_LIVE_DAILY_LIMIT)
        # One answer at a time. A second wake word while we're still thinking is
        # dropped, not queued: replying to a 30-second-old question after the
        # conversation moved on is worse than staying quiet.
        self._answering = asyncio.Lock()
        self._last_wav_path: str | None = None
        logger.info("VoiceLive cog initialized (enabled=%s, everyone=%s)",
                    VOICE_LIVE_ENABLED, VOICE_LIVE_ALLOW_EVERYONE)

    @commands.Cog.listener()
    async def on_ready(self):
        if VOICE_LIVE_ENABLED and not self.poll.is_running():
            self.poll.start()

    def cog_unload(self):
        if self.poll.is_running():
            self.poll.cancel()

    # ----------------------------------------------------------------- plumbing
    def _recorder(self):
        """The VoiceRecord cog, or None when it isn't loaded."""
        return self.bot.get_cog("VoiceRecord")

    def _live_context(self):
        """``(vc, sink, guild)`` while a recording is running, else None."""
        rec = self._recorder()
        if rec is None or rec.vc is None or rec.sink is None or rec.channel is None:
            return None
        if not rec.vc.is_connected():
            return None
        return rec.vc, rec.sink, rec.channel.guild

    def _allowed(self, member) -> bool:
        """True when ``member`` may summon the bot by voice.

        Admin/owner-only by default — the same gate as vision in text summons.
        Checked *before* transcription so other people's speech never reaches
        (or is billed by) Whisper.
        """
        if VOICE_LIVE_ALLOW_EVERYONE:
            return True
        if member is None:
            return False
        if member.id == MOMENTUM_OWNER_ID:
            return True
        return bool(getattr(getattr(member, "guild_permissions", None),
                            "administrator", False))

    # --------------------------------------------------------------------- loop
    @tasks.loop(seconds=_POLL_SECONDS)
    async def poll(self):
        """Drain finished utterances from the sink and dispatch them.

        Polling rather than a callback from the sink is deliberate: a speaking
        turn is only closed by the *next* frame after a gap, so the last sentence
        before silence would never fire a callback. See
        ``MixingWaveSink.take_finished_utterances``.
        """
        ctx = self._live_context()
        if ctx is None:
            if self._window:
                self._window.clear()   # the call ended; next one starts fresh
            return
        _vc, sink, guild = ctx
        try:
            utterances = sink.take_finished_utterances(time.perf_counter(), _GAP_SECONDS)
        except Exception:
            logger.exception("Reading live utterances from the sink failed")
            return
        for utt in utterances:
            member = guild.get_member(utt["user_id"]) if utt["user_id"] else None
            can_summon = self._allowed(member)
            if not (can_summon or VOICE_LIVE_CONTEXT_FROM_ALL):
                continue  # not allowed to summon and we don't buy context — drop
            # Never block the poll loop: STT + model + TTS run as their own task.
            asyncio.create_task(self._handle(utt, member, can_summon))

    @poll.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ handling
    async def _handle(self, utt: dict, member, can_summon: bool):
        """Transcribe one utterance, and answer it if it summoned the bot.

        Fire-and-forget task: an unguarded exception here would vanish without a
        trace (the same lesson as ``voicerecord._finish_and_publish``), and the
        whole chain is time-boxed because answering long after the moment has
        passed is worse than silence.
        """
        try:
            await asyncio.wait_for(self._handle_inner(utt, member, can_summon),
                                   timeout=VOICE_LIVE_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning("Live reply dropped: over %ss for a %.1fs utterance from %s",
                           VOICE_LIVE_TIMEOUT_S, utt.get("seconds", 0), utt.get("name"))
        except Exception:
            logger.exception("Live voice handling failed")

    async def _handle_inner(self, utt: dict, member, can_summon: bool):
        if not transcribe.is_configured():
            return
        text = await self._transcribe(utt)
        if not text:
            return
        speaker = member.display_name if member else utt["name"]
        self._window.append({
            "author_id": utt["user_id"] or 0,
            "display_name": speaker,
            "is_bot": False,
            "content": text,
        })
        logger.debug("Live utterance [%s]: %s", speaker, text)

        if not can_summon or not voice_live.has_wake_word(text):
            return
        if self._answering.locked():
            logger.info("Wake word from %s ignored — still answering the previous one",
                        speaker)
            return
        async with self._answering:
            await self._answer(text, member, speaker)

    async def _transcribe(self, utt: dict) -> str:
        """Whisper one buffered utterance. Returns "" on any failure."""
        fd, path = tempfile.mkstemp(suffix=".wav", dir=tempfile.gettempdir())
        os.close(fd)
        try:
            await asyncio.to_thread(voice_live.pcm_to_wav, utt["pcm"], path)
            return (await asyncio.to_thread(transcribe.transcribe, path)) or ""
        except Exception as e:
            if transcribe.is_quota_error(str(e)):
                logger.error("Live STT: OpenAI credits exhausted — voice replies "
                             "are down until the account is topped up")
            else:
                logger.error("Live STT failed: %s", e)
            return ""
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    async def _answer(self, question: str, member, speaker: str):
        """Generate a reply to a wake-worded utterance and speak it."""
        user_id = member.id if member else 0
        is_owner = user_id == MOMENTUM_OWNER_ID
        day = datetime.now(self.warsaw).date().isoformat()
        if not is_owner and not self._limiter.allow(user_id, day):
            # No graceful way to decline out loud without eating the meeting's
            # time — take the silence.
            logger.info("Daily live-voice limit reached for %s", user_id)
            return

        logger.info("Live summon from %s: %s", speaker, question)
        user_msg = voice_live.build_voice_prompt(
            build_summon_prompt(list(self._window), self.bot.user.id,
                                direct_mention=True)
        )
        reply = await asyncio.to_thread(
            przywolanie.generate_reply, user_msg, day, False, True
        )
        speech = voice_live.strip_for_speech(reply or "")
        if not speech:
            logger.info("Model returned nothing speakable — staying quiet")
            return
        if not tts.is_configured():
            return
        await self._speak(speech)
        # Let the model see what it already said, so a follow-up doesn't repeat it.
        self._window.append({
            "author_id": self.bot.user.id,
            "display_name": "Momentum",
            "is_bot": True,
            "content": speech,
        })

    # ------------------------------------------------------------------ speaking
    async def _speak(self, text: str):
        """Synthesize ``text`` and play it into the call, mixing it into the WAV."""
        ctx = self._live_context()
        if ctx is None:
            return   # the call ended while we were thinking
        vc, sink, _guild = ctx
        try:
            mp3 = await asyncio.to_thread(tts.synthesize, text)
        except Exception as e:
            if transcribe.is_quota_error(str(e)):
                logger.error("TTS: OpenAI credits exhausted — voice replies are down")
            else:
                logger.error("TTS failed: %s", e)
            return
        if not mp3:
            return
        try:
            if vc.is_playing():
                _stop_playing(vc)
            source = TeeSource(discord.FFmpegPCMAudio(mp3), sink.write_bot_frame)
            vc.play(source)
            await self._wait_or_yield(vc, sink)
            # Tripwire for the class of bug that cost a live recording on
            # 13.09.2026 (see _stop_playing): if anything on the playback path
            # ever kills the listener again, say so instead of going quietly deaf.
            if not vc.is_listening():
                logger.error("Recording STOPPED by the playback path — the sink is "
                             "no longer listening after a live reply. This is a bug.")
        except Exception:
            logger.exception("Playing the live reply failed")
        finally:
            try:
                os.remove(mp3)
            except OSError:
                pass

    async def _wait_or_yield(self, vc, sink):
        """Wait out the playback, stopping early if a person talks over the bot.

        Barge-in needs *sustained* speech: on a live call someone laughs or says
        "no właśnie" constantly, and a single-frame trigger would cut the bot off
        mid-sentence every time. We require VOICE_LIVE_BARGEIN_SECONDS of
        continuous human audio before yielding the floor — then yield it
        immediately, because a person always outranks the bot.

        The grace period exists because the asker is often still making noise
        when the reply lands seconds after their question: on the first live test
        the bot got cut off after one word ("Jestem") by the tail of the very
        question it was answering. Nothing can barge in before the bot has had a
        moment to start.
        """
        needed = max(1, int(VOICE_LIVE_BARGEIN_SECONDS / _POLL_SECONDS))
        started = time.perf_counter()
        streak = 0
        while vc.is_playing():
            await asyncio.sleep(_POLL_SECONDS)
            if time.perf_counter() - started < _BARGEIN_GRACE_SECONDS:
                continue
            talking = (time.perf_counter() - sink.last_human_frame) < _FRESH_SECONDS
            streak = streak + 1 if talking else 0
            if streak >= needed:
                logger.info("Barge-in — someone started talking, stopping playback")
                _stop_playing(vc)
                return


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceLive(bot))
