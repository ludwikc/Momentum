import unittest

from digest import build_digest_messages, build_dm_text, select_daily_meetings


class SelectDailyMeetingsTest(unittest.TestCase):
    ITEMS = [
        {"id": "a", "data": "2026-08-07 12:34", "kanal": "🔢│1234-daily-coaching", "uczestnicy": ["A"]},
        {"id": "b", "data": "2026-08-05 06:31", "kanal": "warsztaty-lifehackerow", "uczestnicy": ["B"]},
        {"id": "c", "data": "2026-08-04 12:35", "kanal": "1234-daily-coaching", "uczestnicy": ["C"]},
    ]

    def test_keeps_only_daily_coaching_in_order(self):
        got = select_daily_meetings(self.ITEMS, channel_key="1234-daily-coaching")
        self.assertEqual([m["id"] for m in got], ["a", "c"])

    def test_empty_input(self):
        self.assertEqual(select_daily_meetings([], channel_key="x"), [])


class BuildDigestMessagesTest(unittest.TestCase):
    MEETINGS = [
        {"data": "2026-08-04 12:35", "uczestnicy": ["Ala", "Ola"], "body": "**Ala:** gadamy o nawykach"},
        {"data": "2026-08-07 12:34", "uczestnicy": ["Ala"], "body": "**Ala:** upały i produktywność"},
    ]

    def test_system_prompt_carries_style_anchors(self):
        system, _ = build_digest_messages(self.MEETINGS, week_label="03.08–09.08")
        for anchor in ("@LIFEHACKERZY", "Wy/Was/Wam", "[LINK]", "WYŁĄCZNIE gotowy post", "ZAKAZ", "KOTWICA"):
            self.assertIn(anchor, system)

    def test_user_prompt_carries_meetings_and_label(self):
        _, user = build_digest_messages(self.MEETINGS, week_label="03.08–09.08")
        self.assertIn("03.08–09.08", user)
        self.assertIn("2026-08-04 12:35", user)
        self.assertIn("Ala, Ola", user)
        self.assertIn("upały i produktywność", user)


class BuildDmTextTest(unittest.TestCase):
    def test_wraps_post_in_code_block(self):
        dm = build_dm_text("@LIFEHACKERZY\n## Tydzień rozkminek\n- bullet")
        self.assertIn("```markdown\n@LIFEHACKERZY", dm)
        self.assertTrue(dm.rstrip().endswith("```"))

    def test_lists_link_placeholder_when_present(self):
        dm = build_dm_text("@LIFEHACKERZY\n## X\n- y\n\n[LINK]")
        self.assertIn("[LINK]", dm.split("```")[-1])
