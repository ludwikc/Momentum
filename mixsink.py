# mixsink.py
# A real-time mixing audio sink for discord-ext-voice-recv.
#
# Why this exists
# ---------------
# The library's WaveSink (even wrapped in SilenceGeneratorSink) is the wrong tool
# for a multi-person call, for two independent reasons:
#
#   1. No mixing. The packet router pops one 20 ms frame per *speaker* each cycle
#      and calls sink.write() for each, and WaveSink simply appends them to one
#      mono-timeline file. An N-speaker call therefore produces an ~N x too long
#      file with everyone's audio serialized one-after-another instead of overlaid.
#
#   2. Concurrent writes. SilenceGeneratorSink runs a *second thread* that also
#      calls WaveSink.write() (to fill gaps with silence) while the router thread
#      is writing. Python's wave module is not thread-safe, so on a busy call the
#      two threads race and corrupt the file header.
#
# How frames are placed on the timeline (the quality fix)
# -------------------------------------------------------
# Each frame must land at its *true* position in the call, or the mix crackles and
# drifts. There are two clocks we could use:
#
#   * wall-clock arrival time (time.perf_counter() when write() runs) — WRONG.
#     Network jitter, GC pauses and asyncio/ffmpeg scheduling delays smear arrival
#     times by tens to hundreds of ms. Two consecutive 20 ms frames that arrive in
#     a burst collapse into one tick and get *summed* (overlapped) -> audible
#     crackle; a frame that arrives late gets shoved forward and overwrites a later
#     one -> time-compression and cut-offs. This is what the old version did.
#
#   * the RTP timestamp on each packet (data.packet.timestamp) — CORRECT, and what
#     Craig uses. Discord stamps every voice packet with a 48 kHz sample counter
#     that advances by exactly 960 samples (20 ms) per frame, per speaker, wholly
#     independent of when the packet happens to reach us. Positioning by RTP
#     timestamp makes intra-speaker placement jitter-free: consecutive frames never
#     collide, and when someone stops talking the timestamp simply jumps, so the
#     gap is reconstructed as exact silence instead of being compressed away.
#
# MixingWaveSink anchors each speaker's first packet to the global wall clock (so a
# latecomer lands at the right offset in the call) and then positions every
# subsequent frame of that speaker purely by RTP-timestamp delta. Frames are summed
# (with saturation) onto a single shared 20 ms-tick timeline, gaps are filled with
# silence, and the file is written by the router thread only (no SilenceGeneratorSink,
# so no concurrent-write race). The output is a normal 48 kHz/stereo/16-bit WAV of
# the real call length, ready for the existing transcode/transcribe/upload pipeline.

import audioop
import json
import logging
import threading
import time
import wave
from typing import Optional

from discord.ext import voice_recv

from config import (
    DIARIZATION_GAP_FRAMES,
    MOMENTUM_BOT_ID,
    VOICE_LIVE_MAX_SECONDS,
    VOICE_LIVE_MIN_SECONDS,
)

logger = logging.getLogger("momentum_bot.mixsink")

_RATE = 48000
_CHANNELS = 2
_WIDTH = 2
_FRAME_BYTES = 3840            # 20 ms @ 48 kHz stereo 16-bit (Decoder.FRAME_SIZE)
_FRAME_SECONDS = 0.02
_RTP_PER_FRAME = 960           # RTP timestamp units (48 kHz samples) per 20 ms frame
_RTP_MODULO = 1 << 32          # RTP timestamps are unsigned 32-bit and wrap around
_SILENCE = b"\x00" * _FRAME_BYTES
# How far behind the newest tick we keep buckets open before writing them to disk.
# Only bounds memory and flush latency (the recording is not played in real time),
# so it can be generous: it just has to exceed the jitter-buffer reordering depth
# and any cross-speaker arrival skew. 100 frames = 2 s.
_REORDER_FRAMES = 100
# A frame's true position can never be ahead of the wall clock (audio is captured
# in the past and reaches us *delayed* by the jitter buffer). We clamp any computed
# tick to the current wall-clock tick plus this slack, so a corrupt/out-of-range RTP
# timestamp (bit-flip, ssrc reset) can't jump the write head minutes into the future
# — which would write a flood of silence and bury all subsequent real audio. The
# slack only has to absorb rounding at the per-speaker anchor. 50 frames = 1 s.
_FUTURE_GUARD_FRAMES = 50
# ssrc reserved for audio the bot itself plays into the call (see write_bot_frame).
# Discord never assigns 0, so this can't collide with a real speaker.
_BOT_SSRC = 0
# Live-tap bounds, in bytes, derived from the config seconds.
_MAX_LIVE_BYTES = int(VOICE_LIVE_MAX_SECONDS / _FRAME_SECONDS) * _FRAME_BYTES
_MIN_LIVE_BYTES = int(VOICE_LIVE_MIN_SECONDS / _FRAME_SECONDS) * _FRAME_BYTES
# A gap longer than this between two bot frames means a new playback started, so
# the bot write head re-anchors to the wall clock instead of continuing.
_BOT_REANCHOR_SECONDS = 1.0
# A live buffer this old means nobody is draining it — cogs/voice_live.py failed to
# load, or its loop died. Evict rather than grow: the sink must never hold audio
# hostage for a consumer that isn't there. The real consumer polls every 0.25 s,
# so this threshold is orders of magnitude beyond normal.
_LIVE_STALE_SECONDS = 60.0


class _BotSpeaker:
    """Stand-in "member" for the bot, so _track_speaker needs no special case.

    It reads identity via getattr (display_name / name / id), so any object with
    those attributes works.
    """
    __slots__ = ()
    id = MOMENTUM_BOT_ID
    display_name = "Momentum"
    name = "Momentum"


_BOT_SPEAKER = _BotSpeaker()


class MixingWaveSink(voice_recv.AudioSink):
    """Sums all speakers onto one RTP-timestamped timeline and writes a single WAV."""

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self._wav = wave.open(path, "wb")
        self._wav.setnchannels(_CHANNELS)
        self._wav.setsampwidth(_WIDTH)
        self._wav.setframerate(_RATE)
        self._t0: Optional[float] = None      # wall clock of the very first frame
        # Per-speaker (keyed by ssrc) anchors: the tick its stream starts at on the
        # global timeline, and the RTP timestamp of that first frame. Subsequent
        # frames are positioned by RTP-timestamp delta from these.
        self._base_tick: dict[int, int] = {}
        self._base_rtp: dict[int, int] = {}
        self._buckets: dict[int, bytes] = {}
        self._next_tick = 0       # next tick index still to be written to disk
        self._max_tick = -1       # highest tick placed so far (drives flushing)
        self._lock = threading.Lock()
        self._closed = False
        # Diarization side-channel. Discord tells us which member every frame came
        # from, so we record a speaking timeline (ground truth, no acoustic ML) and
        # write it next to the WAV for the transcriber to attribute speakers by time.
        # None of this touches the audio mix above — it's a pure observer.
        self._speakers: dict[int, dict] = {}      # ssrc -> {"id", "name"}
        self._open_seg: dict[int, dict] = {}      # ssrc -> {"start", "last"} (ticks)
        self._segments: list[dict] = []           # finalized {"ssrc","start","end"}
        # Live side-channel (cogs/voice_live.py). Also a pure observer of the mix:
        # per-speaker PCM is buffered so the cog can poll for finished utterances
        # while the call is still running. Off unless the cog turns it on.
        self.live_enabled = False
        self._live: dict[int, dict] = {}          # ssrc -> {"user_id","name","pcm","first_tick","last_wall"}
        # perf_counter() of the most recent frame from a *human*. Barge-in reads
        # this to know a person started talking over the bot.
        self.last_human_frame = 0.0
        # Write head for the bot's own speech (see write_bot_frame): its frames are
        # contiguous by construction, so they advance by exactly one tick each
        # rather than being re-derived from a jittery wall clock per frame.
        self._bot_next_tick: Optional[int] = None
        self._bot_last_wall = 0.0

    def wants_opus(self) -> bool:
        return False              # we need decoded PCM to mix

    def _tick_for(self, ssrc: int, rtp_ts: int, now: float) -> int:
        """Map a packet's RTP timestamp to its 20 ms tick on the global timeline.

        Caller must hold self._lock.
        """
        if ssrc not in self._base_rtp:
            # First frame from this speaker: anchor it to where we are in the call
            # right now (wall clock), so someone who starts speaking 5 min in lands
            # 5 min in rather than at t=0.
            base_tick = int(round((now - self._t0) / _FRAME_SECONDS))
            self._base_tick[ssrc] = base_tick
            self._base_rtp[ssrc] = rtp_ts
            return base_tick
        # Delta in RTP units, accounting for the unsigned 32-bit wraparound.
        delta = (rtp_ts - self._base_rtp[ssrc]) % _RTP_MODULO
        if delta > _RTP_MODULO // 2:          # wrapped backwards (reordered packet)
            delta -= _RTP_MODULO
        return self._base_tick[ssrc] + int(round(delta / _RTP_PER_FRAME))

    def write(self, user, data) -> None:
        pcm = getattr(data, "pcm", None)
        if not pcm:
            return
        packet = getattr(data, "packet", None)
        rtp_ts = getattr(packet, "timestamp", None)
        ssrc = getattr(packet, "ssrc", None)
        # Normalize to exactly one 20 ms frame so summed buckets stay aligned.
        if len(pcm) < _FRAME_BYTES:
            pcm = pcm + _SILENCE[len(pcm):]
        elif len(pcm) > _FRAME_BYTES:
            pcm = pcm[:_FRAME_BYTES]

        now = time.perf_counter()
        with self._lock:
            if self._closed:
                return
            if self._t0 is None:
                self._t0 = now

            if rtp_ts is None or ssrc is None:
                # No usable RTP header (shouldn't happen for real audio): fall back
                # to appending at the current write head so we never drop audio.
                tick = max(self._next_tick, self._max_tick + 1)
            else:
                tick = self._tick_for(ssrc, rtp_ts, now)

            # A real frame is never ahead of the wall clock; clamp so a glitched
            # timestamp can't fling the write head into the future (see constant).
            wall_tick = int(round((now - self._t0) / _FRAME_SECONDS))
            if tick > wall_tick + _FUTURE_GUARD_FRAMES:
                tick = wall_tick + _FUTURE_GUARD_FRAMES
            if tick < self._next_tick:
                tick = self._next_tick          # arrived too late to place exactly
            if tick > self._max_tick:
                self._max_tick = tick
            existing = self._buckets.get(tick)
            self._buckets[tick] = audioop.add(existing, pcm, _WIDTH) if existing else pcm
            # Record who spoke at this tick (diarization side-channel — see __init__).
            if ssrc is not None:
                self._track_speaker(ssrc, user, tick)
            # Live side-channels: a person is talking right now (barge-in), and
            # their audio is buffered for on-the-fly transcription.
            self.last_human_frame = now
            if self.live_enabled and ssrc is not None:
                self._live_append(ssrc, user, pcm, tick, now)
            # Finalize ticks that are safely behind the newest audio we've placed.
            self._flush_through(self._max_tick - _REORDER_FRAMES)

    def _track_speaker(self, ssrc: int, user, tick: int) -> None:
        """Note that `ssrc` was speaking at `tick`, coalescing into turns.

        Caller must hold self._lock.
        """
        # Refresh the speaker's identity whenever the router resolves it (the first
        # frames of a stream can arrive before the member is known).
        name = getattr(user, "display_name", None) or getattr(user, "name", None)
        if name and self._speakers.get(ssrc, {}).get("name") != name:
            self._speakers[ssrc] = {"id": getattr(user, "id", None), "name": name}

        seg = self._open_seg.get(ssrc)
        if seg is None:
            self._open_seg[ssrc] = {"start": tick, "last": tick}
        elif tick - seg["last"] <= DIARIZATION_GAP_FRAMES:
            seg["last"] = max(seg["last"], tick)      # same turn — extend it
        else:
            # Gap too large: close the previous turn and open a new one. `end` is
            # exclusive (last spoken tick + 1).
            self._segments.append({"ssrc": ssrc, "start": seg["start"], "end": seg["last"] + 1})
            self._open_seg[ssrc] = {"start": tick, "last": tick}

    # ----------------------------------------------------------------- live tap
    # Everything below serves cogs/voice_live.py (Momentum answering out loud
    # mid-call). Like the diarization side-channel above, the live buffers are a
    # pure observer of the mix; write_bot_frame is the one *input*, and it goes
    # through the same bucket/diarization path as any other speaker.

    def _live_append(self, ssrc: int, user, pcm: bytes, tick: int, now: float) -> None:
        """Buffer one frame of a speaker's in-progress utterance.

        Caller must hold self._lock.
        """
        buf = self._live.get(ssrc)
        if buf is None:
            buf = self._live[ssrc] = {
                "user_id": getattr(user, "id", None),
                "name": (getattr(user, "display_name", None)
                         or getattr(user, "name", None) or f"User-{ssrc}"),
                "pcm": bytearray(),
                "first_tick": tick,
                "last_wall": now,
            }
        elif buf["user_id"] is None:
            # The router can resolve the member a few frames into a stream; take
            # the identity as soon as it lands (same reason _track_speaker does).
            buf["user_id"] = getattr(user, "id", None)
            name = getattr(user, "display_name", None) or getattr(user, "name", None)
            if name:
                buf["name"] = name
        buf["last_wall"] = now
        if len(buf["pcm"]) < _MAX_LIVE_BYTES:
            buf["pcm"] += pcm
        # Self-heal when there is no consumer (see _LIVE_STALE_SECONDS).
        stale = [s for s, b in self._live.items() if now - b["last_wall"] > _LIVE_STALE_SECONDS]
        for s in stale:
            del self._live[s]
        if stale:
            logger.warning("Dropped %d stale live buffer(s) — is voice_live running?",
                           len(stale))

    def take_finished_utterances(self, now: float, gap_seconds: float) -> list[dict]:
        """Pop and return the buffers of speakers silent for at least `gap_seconds`.

        Called from the cog's polling loop rather than pushed from here on
        purpose: a turn is only *closed* by the arrival of the next frame after a
        gap, so when someone finishes a sentence and the room goes quiet, no
        further frame ever arrives — a callback-based design would sit on that
        last utterance forever. Polling closes it on the clock instead.

        Buffers shorter than VOICE_LIVE_MIN_SECONDS are dropped (a cough, an
        "mhm" — nothing worth an API call). Each returned dict is
        ``{"user_id", "name", "pcm", "start", "seconds"}`` with ``start`` in
        seconds from the beginning of the recording.
        """
        out: list[dict] = []
        with self._lock:
            if self._closed:
                return out
            done = [s for s, b in self._live.items() if now - b["last_wall"] >= gap_seconds]
            for ssrc in done:
                buf = self._live.pop(ssrc)
                pcm = bytes(buf["pcm"])
                if len(pcm) < _MIN_LIVE_BYTES:
                    continue
                out.append({
                    "user_id": buf["user_id"],
                    "name": buf["name"],
                    "pcm": pcm,
                    "start": round(buf["first_tick"] * _FRAME_SECONDS, 2),
                    "seconds": round(len(pcm) / (_RATE * _CHANNELS * _WIDTH), 2),
                })
        return out

    def write_bot_frame(self, pcm: bytes) -> None:
        """Mix one 20 ms frame of the bot's *own* speech into the recording.

        voice_recv never loops our outgoing audio back, so without this the bot
        would speak in the call and be absent from its archive: no words in the
        transcript, no turn in the diarization, nothing in the AI summary — the
        recording would quietly misrepresent the meeting. Fed frame-by-frame from
        cogs/voice_live.py's TeeSource while vc.play() runs.

        Bot audio is generated locally (no RTP, no jitter buffer), so placement
        anchors once to the wall clock and then advances one tick per frame —
        the frames are contiguous by construction, and re-deriving each from a
        jittery clock would collide two of them into one bucket (a doubled,
        distorted frame) or leave holes. _track_speaker then labels the run under
        a reserved ssrc, so everything downstream sees a normal speaker called
        "Momentum" with no special case.
        """
        if not pcm:
            return
        if len(pcm) < _FRAME_BYTES:
            pcm = pcm + _SILENCE[len(pcm):]
        elif len(pcm) > _FRAME_BYTES:
            pcm = pcm[:_FRAME_BYTES]

        now = time.perf_counter()
        with self._lock:
            if self._closed:
                return
            if self._t0 is None:
                self._t0 = now
            if (self._bot_next_tick is None
                    or now - self._bot_last_wall > _BOT_REANCHOR_SECONDS):
                self._bot_next_tick = int(round((now - self._t0) / _FRAME_SECONDS))
            self._bot_last_wall = now

            tick = max(self._bot_next_tick, self._next_tick)
            self._bot_next_tick = tick + 1
            if tick > self._max_tick:
                self._max_tick = tick
            existing = self._buckets.get(tick)
            self._buckets[tick] = audioop.add(existing, pcm, _WIDTH) if existing else pcm
            self._track_speaker(_BOT_SSRC, _BOT_SPEAKER, tick)
            self._flush_through(self._max_tick - _REORDER_FRAMES)

    def _flush_through(self, up_to: int) -> None:
        """Write every tick up to `up_to` in order, filling gaps with silence.

        Caller must hold self._lock.
        """
        while self._next_tick <= up_to:
            self._wav.writeframes(self._buckets.pop(self._next_tick, _SILENCE))
            self._next_tick += 1

    def cleanup(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._live.clear()      # the call is over; nothing left to answer
            last = max(self._buckets) if self._buckets else self._next_tick - 1
            self._flush_through(last)
            try:
                self._wav.close()
            except Exception as e:
                logger.error("Error closing mixed wav %s: %s", self.path, e)
            self._write_diarization_sidecar()
        logger.info("Mixed recording finalized: %s (%d frames, %.1f s)",
                    self.path, self._next_tick, self._next_tick * _FRAME_SECONDS)

    def _write_diarization_sidecar(self) -> None:
        """Write the speaking timeline to `<wav>.diarization.json` (best-effort).

        Caller must hold self._lock. Never raises — a missing sidecar just means the
        transcript falls back to its un-labeled form.
        """
        # Close any still-open turns.
        segments = list(self._segments)
        for ssrc, seg in self._open_seg.items():
            segments.append({"ssrc": ssrc, "start": seg["start"], "end": seg["last"] + 1})
        if not segments:
            return
        segments.sort(key=lambda s: s["start"])
        out = []
        for s in segments:
            who = self._speakers.get(s["ssrc"], {})
            out.append({
                "start": round(s["start"] * _FRAME_SECONDS, 2),
                "end": round(s["end"] * _FRAME_SECONDS, 2),
                "user_id": who.get("id"),
                "name": who.get("name") or f"User-{s['ssrc']}",
            })
        path = self.path + ".diarization.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"frame_seconds": _FRAME_SECONDS, "segments": out}, f, ensure_ascii=False)
            logger.info("Diarization timeline written: %s (%d segments)", path, len(out))
        except Exception as e:
            logger.error("Failed to write diarization sidecar %s: %s", path, e)
