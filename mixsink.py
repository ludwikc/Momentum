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

from config import DIARIZATION_GAP_FRAMES

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
