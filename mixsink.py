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
#      two threads race and corrupt the file header — which is exactly why the
#      2026-06-23 daily-coaching recording came out unreadable ("Invalid data
#      found when processing input") and never made it to Drive. A one-person call
#      has almost no traffic, so the race rarely triggers — which is why solo tests
#      and the single-presenter morning session looked fine.
#
# MixingWaveSink fixes both: it sums every speaker's frame onto a single shared
# timeline (bucketed by arrival time into 20 ms ticks, summed with saturation),
# fills gaps with silence so the timeline stays real-time accurate, and is written
# by only the router thread (no SilenceGeneratorSink), so the file is never
# written concurrently. The output is a normal 48 kHz/stereo/16-bit WAV of the
# real call length, ready for the existing transcode/transcribe/upload pipeline.

import audioop
import logging
import threading
import time
import wave
from typing import Optional

from discord.ext import voice_recv

logger = logging.getLogger("momentum_bot.mixsink")

_RATE = 48000
_CHANNELS = 2
_WIDTH = 2
_FRAME_BYTES = 3840            # 20 ms @ 48 kHz stereo 16-bit (Decoder.FRAME_SIZE)
_FRAME_SECONDS = 0.02
_SILENCE = b"\x00" * _FRAME_BYTES
_REORDER_FRAMES = 10          # 200 ms jitter window before a tick is finalized


class MixingWaveSink(voice_recv.AudioSink):
    """Sums all speakers onto one timeline and writes a single WAV file."""

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self._wav = wave.open(path, "wb")
        self._wav.setnchannels(_CHANNELS)
        self._wav.setsampwidth(_WIDTH)
        self._wav.setframerate(_RATE)
        self._t0: Optional[float] = None
        self._buckets: dict[int, bytes] = {}
        self._next_tick = 0       # next tick index still to be written to disk
        self._lock = threading.Lock()
        self._closed = False

    def wants_opus(self) -> bool:
        return False              # we need decoded PCM to mix

    def write(self, user, data) -> None:
        pcm = getattr(data, "pcm", None)
        if not pcm:
            return
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
            tick = int(round((now - self._t0) / _FRAME_SECONDS))
            if tick < self._next_tick:
                tick = self._next_tick          # arrived too late to place exactly
            existing = self._buckets.get(tick)
            self._buckets[tick] = audioop.add(existing, pcm, _WIDTH) if existing else pcm
            # Finalize ticks older than the reorder window.
            self._flush_through(tick - _REORDER_FRAMES)

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
        logger.info("Mixed recording finalized: %s (%d frames, %.1f s)",
                    self.path, self._next_tick, self._next_tick * _FRAME_SECONDS)
