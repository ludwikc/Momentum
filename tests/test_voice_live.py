"""Tests for the live voice-reply helpers (voice_live.py + the mixsink live tap).

The sink tests need discord-ext-voice-recv, which only the project venv has, so
they skip cleanly under a bare `python3 -m unittest discover tests` and run for
real under `venv/bin/python -m unittest discover tests` (what a deploy check uses).
"""
import os
import sys
import tempfile
import time
import unittest
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voice_live import (
    VOICE_MODE_INSTRUCTION,
    build_voice_prompt,
    has_wake_word,
    normalize_word,
    pcm_to_wav,
    strip_for_speech,
)

try:
    from mixsink import _FRAME_BYTES, MixingWaveSink
    _HAS_VOICE_RECV = True
except ImportError:  # pragma: no cover - system python without voice_recv
    _HAS_VOICE_RECV = False


class TestNormalizeWord(unittest.TestCase):
    def test_strips_punctuation_and_case(self):
        self.assertEqual(normalize_word("Momentum,"), "momentum")
        self.assertEqual(normalize_word("„Momentum”."), "momentum")
        self.assertEqual(normalize_word("MOMENTUM!"), "momentum")

    def test_keeps_polish_letters(self):
        self.assertEqual(normalize_word("Zażółć,"), "zażółć")

    def test_pure_punctuation_is_empty(self):
        self.assertEqual(normalize_word("—"), "")


class TestHasWakeWord(unittest.TestCase):
    def test_leading_wake_word(self):
        self.assertTrue(has_wake_word("Momentum, co o tym myślisz?"))
        self.assertTrue(has_wake_word("momentum"))

    def test_short_lead_in_still_works(self):
        self.assertTrue(has_wake_word("Hej Momentum, co sądzisz?"))
        self.assertTrue(has_wake_word("OK Momentum, powiedz coś."))

    def test_mid_sentence_mention_is_ignored(self):
        # The whole point of the positional rule: on a text channel this would
        # summon the bot, on voice it must not make it speak over the room.
        self.assertFalse(has_wake_word("Tak, myślę że Momentum to dobry pomysł"))
        self.assertFalse(
            has_wake_word("Wczoraj rozmawialiśmy o tym, że Momentum nagrywa spotkania")
        )

    def test_known_false_positive_inside_the_window(self):
        # Inherent to any positional rule: "No i Momentum powiedział" cannot be
        # told apart from "Hej no Momentum, …" by position alone. Documented
        # rather than worked around; tighten the window to trade it off.
        self.assertTrue(has_wake_word("No i Momentum powiedział"))
        self.assertFalse(has_wake_word("No i Momentum powiedział", window=1))

    def test_punctuation_does_not_consume_a_slot(self):
        self.assertTrue(has_wake_word("— Momentum, co myślisz?"))

    def test_wider_window_restores_loose_matching(self):
        self.assertTrue(
            has_wake_word("Tak, myślę że Momentum to dobry pomysł", window=99)
        )

    def test_empty_and_degenerate_inputs(self):
        self.assertFalse(has_wake_word(""))
        self.assertFalse(has_wake_word("cokolwiek", window=0))
        self.assertFalse(has_wake_word("momentum", words=()))


class TestStripForSpeech(unittest.TestCase):
    def test_removes_discord_tokens(self):
        out = strip_for_speech("Cześć <@404038151565213696>, zajrzyj na <#123456>!")
        self.assertNotIn("<@", out)
        self.assertNotIn("<#", out)
        self.assertIn("Cześć", out)

    def test_removes_custom_emoji(self):
        self.assertNotIn(":", strip_for_speech("Super <:momentum:987654321>"))

    def test_strips_markdown(self):
        out = strip_for_speech("**Ważne**: zrób to _dzisiaj_ i `sprawdź`")
        self.assertNotIn("*", out)
        self.assertNotIn("`", out)
        self.assertIn("Ważne", out)
        self.assertIn("dzisiaj", out)

    def test_strips_bullets_and_headings(self):
        out = strip_for_speech("# Nagłówek\n- pierwszy\n2. drugi\n> cytat")
        for line in out.splitlines():
            self.assertFalse(line.startswith(("#", "-", ">")), line)
        self.assertIn("pierwszy", out)

    def test_urls_become_the_word_link(self):
        out = strip_for_speech("Szczegóły tutaj: https://siadlak.vip/kurs?a=1")
        self.assertNotIn("http", out)
        self.assertIn("link", out)

    def test_markdown_link_keeps_its_label(self):
        out = strip_for_speech("Zobacz [kurs Momentum](https://siadlak.vip)")
        self.assertIn("kurs Momentum", out)
        self.assertNotIn("http", out)

    def test_code_block_dropped(self):
        out = strip_for_speech("Tak:\n```python\nprint(1)\n```\nI tyle.")
        self.assertNotIn("print", out)
        self.assertIn("I tyle.", out)

    def test_truncates_on_a_sentence_boundary(self):
        out = strip_for_speech("Zdanie testowe. " * 50, limit=600)
        self.assertLessEqual(len(out), 600)
        self.assertTrue(out.endswith("."), out[-20:])

    def test_truncates_on_a_word_boundary_without_sentences(self):
        out = strip_for_speech("słowo " * 200, limit=600)
        self.assertLessEqual(len(out), 600)
        self.assertTrue(out.endswith("słowo"), out[-20:])

    def test_short_text_untouched(self):
        self.assertEqual(strip_for_speech("Krótko i na temat."), "Krótko i na temat.")

    def test_empty(self):
        self.assertEqual(strip_for_speech(""), "")
        self.assertEqual(strip_for_speech(None), "")


class TestBuildVoicePrompt(unittest.TestCase):
    def test_instruction_goes_last(self):
        out = build_voice_prompt("okno rozmowy\n\nOdezwij się.")
        self.assertTrue(out.startswith("okno rozmowy"))
        self.assertTrue(out.endswith(VOICE_MODE_INSTRUCTION))

    def test_original_prompt_is_preserved(self):
        self.assertIn("Odezwij się.", build_voice_prompt("Odezwij się."))


class TestPcmToWav(unittest.TestCase):
    def test_writes_a_48k_stereo_wav(self):
        pcm = b"\x00" * (3840 * 5)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            pcm_to_wav(pcm, path)
            with wave.open(path, "rb") as wav:
                self.assertEqual(wav.getframerate(), 48000)
                self.assertEqual(wav.getnchannels(), 2)
                self.assertEqual(wav.getsampwidth(), 2)
                self.assertEqual(wav.getnframes(), len(pcm) // 4)
        finally:
            os.remove(path)


class _FakePacket:
    def __init__(self, ssrc, timestamp):
        self.ssrc = ssrc
        self.timestamp = timestamp


class _FakeData:
    def __init__(self, pcm, ssrc, timestamp):
        self.pcm = pcm
        self.packet = _FakePacket(ssrc, timestamp)


class _FakeMember:
    def __init__(self, uid, name):
        self.id = uid
        self.display_name = name
        self.name = name


@unittest.skipUnless(_HAS_VOICE_RECV, "needs discord-ext-voice-recv (project venv)")
class TestSinkLiveTap(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        self.sink = MixingWaveSink(self.path)

    def tearDown(self):
        try:
            self.sink.cleanup()
        except Exception:
            pass
        for p in (self.path, self.path + ".diarization.json"):
            try:
                os.remove(p)
            except OSError:
                pass

    def _speak(self, ssrc, member, frames, start_rtp=1000):
        frame = b"\x01\x00" * (_FRAME_BYTES // 2)
        for i in range(frames):
            self.sink.write(member, _FakeData(frame, ssrc, start_rtp + i * 960))

    def test_disabled_by_default_buffers_nothing(self):
        self._speak(11, _FakeMember(1, "Ludwik"), 50)
        self.assertEqual(
            self.sink.take_finished_utterances(time.perf_counter() + 10, 0.5), []
        )

    def test_two_speakers_two_utterances(self):
        self.sink.live_enabled = True
        self._speak(11, _FakeMember(1, "Ludwik"), 50)
        self._speak(22, _FakeMember(2, "Jakub"), 50, start_rtp=5000)
        out = self.sink.take_finished_utterances(time.perf_counter() + 10, 0.5)
        self.assertEqual(len(out), 2)
        self.assertEqual({u["name"] for u in out}, {"Ludwik", "Jakub"})
        self.assertEqual({u["user_id"] for u in out}, {1, 2})
        for u in out:
            self.assertAlmostEqual(u["seconds"], 1.0, places=1)
            self.assertEqual(len(u["pcm"]), 50 * _FRAME_BYTES)

    def test_still_speaking_is_not_returned(self):
        self.sink.live_enabled = True
        self._speak(11, _FakeMember(1, "Ludwik"), 50)
        self.assertEqual(
            self.sink.take_finished_utterances(time.perf_counter(), 0.5), []
        )

    def test_taken_utterance_is_removed(self):
        self.sink.live_enabled = True
        self._speak(11, _FakeMember(1, "Ludwik"), 50)
        self.assertEqual(
            len(self.sink.take_finished_utterances(time.perf_counter() + 10, 0.5)), 1
        )
        self.assertEqual(
            self.sink.take_finished_utterances(time.perf_counter() + 10, 0.5), []
        )

    def test_too_short_utterance_dropped(self):
        self.sink.live_enabled = True
        self._speak(11, _FakeMember(1, "Ludwik"), 10)   # 0.2 s < VOICE_LIVE_MIN_SECONDS
        self.assertEqual(
            self.sink.take_finished_utterances(time.perf_counter() + 10, 0.5), []
        )

    def test_cleanup_drops_pending_buffers(self):
        self.sink.live_enabled = True
        self._speak(11, _FakeMember(1, "Ludwik"), 50)
        self.sink.cleanup()
        self.assertEqual(
            self.sink.take_finished_utterances(time.perf_counter() + 10, 0.5), []
        )


@unittest.skipUnless(_HAS_VOICE_RECV, "needs discord-ext-voice-recv (project venv)")
class TestSinkBotFrames(unittest.TestCase):
    def test_bot_audio_lands_in_the_mix_and_the_diarization(self):
        import json

        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        sink = MixingWaveSink(path)
        frame = b"\x01\x00" * (_FRAME_BYTES // 2)
        try:
            for _ in range(50):
                sink.write_bot_frame(frame)
            sink.cleanup()
            with wave.open(path, "rb") as wav:
                self.assertEqual(wav.getnframes(), 50 * 960)   # contiguous, no gaps
            with open(path + ".diarization.json", encoding="utf-8") as f:
                segments = json.load(f)["segments"]
            self.assertEqual([s["name"] for s in segments], ["Momentum"])
            self.assertAlmostEqual(segments[0]["end"] - segments[0]["start"], 1.0, places=1)
        finally:
            for p in (path, path + ".diarization.json"):
                try:
                    os.remove(p)
                except OSError:
                    pass


class _FakeVoiceClient:
    """Mimics VoiceRecvClient's critical quirk: stop() also stops listening."""

    def __init__(self, frames_to_play=100):
        self._left = frames_to_play
        self.listening = True
        self.calls: list[str] = []

    def is_playing(self) -> bool:
        self._left -= 1
        return self._left > 0

    def is_listening(self) -> bool:
        return self.listening

    def stop(self):
        self.calls.append("stop")
        self.listening = False      # the trap — see voice_recv voice_client.py:169

    def stop_playing(self):
        self.calls.append("stop_playing")
        self._left = 0


class _FakeSink:
    def __init__(self, talking: bool):
        # perf_counter() far in the past = nobody talking; now = talking.
        self.last_human_frame = time.perf_counter() if talking else 0.0

    def refresh(self):
        self.last_human_frame = time.perf_counter()


@unittest.skipUnless(_HAS_VOICE_RECV, "needs discord (project venv)")
class TestBargeInNeverStopsRecording(unittest.TestCase):
    """Regression for 13.09.2026: barge-in called vc.stop(), which on a
    VoiceRecvClient stops *receiving* too — it killed the live recording 2 ms
    after the bot's first spoken reply, and the bot went deaf while staying in
    the channel. Nothing on the playback path may ever call stop().
    """

    def setUp(self):
        # Compress the real timings (0.25 s poll, 0.75 s grace, 1.0 s streak) so
        # the suite doesn't sleep through them; the logic under test is unchanged.
        from cogs import voice_live as cog_mod
        self._mod = cog_mod
        self._saved = (cog_mod._POLL_SECONDS, cog_mod._BARGEIN_GRACE_SECONDS,
                       cog_mod.VOICE_LIVE_BARGEIN_SECONDS)
        cog_mod._POLL_SECONDS = 0.01
        cog_mod._BARGEIN_GRACE_SECONDS = 0.02
        cog_mod.VOICE_LIVE_BARGEIN_SECONDS = 0.04

    def tearDown(self):
        (self._mod._POLL_SECONDS, self._mod._BARGEIN_GRACE_SECONDS,
         self._mod.VOICE_LIVE_BARGEIN_SECONDS) = self._saved

    def _run(self, talking: bool):
        import asyncio as aio

        from cogs.voice_live import VoiceLive

        cog = VoiceLive.__new__(VoiceLive)          # no bot needed for this path
        vc = _FakeVoiceClient()
        sink = _FakeSink(talking)

        async def drive():
            if talking:
                # Keep "someone is speaking" true for the whole playback.
                async def keep_talking():
                    while vc.is_listening() and vc._left > 0:
                        sink.refresh()
                        await aio.sleep(0.01)
                task = aio.create_task(keep_talking())
                await cog._wait_or_yield(vc, sink)
                task.cancel()
            else:
                await cog._wait_or_yield(vc, sink)

        aio.run(drive())
        return vc

    def test_barge_in_stops_playback_only(self):
        vc = self._run(talking=True)
        self.assertIn("stop_playing", vc.calls)
        self.assertNotIn("stop", vc.calls)
        self.assertTrue(vc.is_listening(), "barge-in must never stop the recording")

    def test_quiet_playback_ends_without_stopping_anything(self):
        vc = self._run(talking=False)
        self.assertNotIn("stop", vc.calls)
        self.assertTrue(vc.is_listening())


if __name__ == "__main__":
    unittest.main()
