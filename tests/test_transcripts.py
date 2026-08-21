import tempfile
import unittest
from datetime import date, datetime

import transcripts
from transcripts import _datetime_of, find_orphans


class DatetimeOfTest(unittest.TestCase):
    def test_frontmatter_format(self):
        self.assertEqual(_datetime_of("2026-08-04 12:34"), datetime(2026, 8, 4, 12, 34))

    def test_filename_stem_format(self):
        self.assertEqual(_datetime_of("2026-08-04_12-34"), datetime(2026, 8, 4, 12, 34))

    def test_date_only_falls_back_to_midnight(self):
        self.assertEqual(_datetime_of("2026-08-04"), datetime(2026, 8, 4))

    def test_garbage_returns_none(self):
        self.assertIsNone(_datetime_of("nie-data"))
        self.assertIsNone(_datetime_of(""))


class ListTranscriptsOrderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = transcripts.TRANSCRIPTS_DIR
        transcripts.TRANSCRIPTS_DIR = self._tmp.name

    def tearDown(self):
        transcripts.TRANSCRIPTS_DIR = self._orig
        self._tmp.cleanup()

    def test_same_day_meetings_sort_newest_first(self):
        transcripts.save_transcript(
            "**A:** rano", started=datetime(2026, 8, 4, 6, 31),
            channel_name="warsztaty", rec_id="aaaaaa",
        )
        transcripts.save_transcript(
            "**B:** poludnie", started=datetime(2026, 8, 4, 12, 34),
            channel_name="daily", rec_id="bbbbbb",
        )
        items = transcripts.list_transcripts(today=date(2026, 8, 4))
        self.assertEqual(
            [i["id"] for i in items],
            ["2026-08-04_12-34_daily_bbbbbb", "2026-08-04_06-31_warsztaty_aaaaaa"],
        )


class FindOrphansTest(unittest.TestCase):
    RECORDINGS = [
        "Lifehackerzy_2026-07-28-06-30-40_warsztaty-lifehackerow_961c1e.wav",
        "Lifehackerzy_2026-07-28-06-30-40_warsztaty-lifehackerow_961c1e.wav.diarization.json",
        "Lifehackerzy_2026-08-06-12-34-01_1234-daily-coaching_c26abe.wav",
        "recording_2026-06-22_21-50-06.wav",  # legacy junk — never an orphan
        "Lifehackerzy_2026-07-23-12-34-46_1234-daily-coaching_497188.mp3",  # mp3 ≠ orphan
    ]
    TRANSCRIPTS = [
        "2026-08-06_12-34_1234-daily-coaching_c26abe.md",
        "2026-07-07_06-32_warsztaty-lifehacker-w_57010a.md",
    ]

    def test_wav_without_transcript_is_orphan(self):
        self.assertEqual(
            find_orphans(self.RECORDINGS, self.TRANSCRIPTS),
            ["Lifehackerzy_2026-07-28-06-30-40_warsztaty-lifehackerow_961c1e.wav"],
        )

    def test_empty_inputs(self):
        self.assertEqual(find_orphans([], []), [])
        self.assertEqual(find_orphans([], self.TRANSCRIPTS), [])
