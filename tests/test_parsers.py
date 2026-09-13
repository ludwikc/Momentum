import unittest
from datetime import date, datetime, timezone

from config import EMBED_FIX_HOSTS
from parsers import (
    parse_date_arg,
    parse_db_timestamp,
    parse_duration_pl,
    parse_index_ranges,
    parse_message_link,
    parse_profile_tags,
    parse_recording_filename,
    parse_wallclock_pl,
    rewrite_bare_social_link,
)


class TestParseDurationPl(unittest.TestCase):
    def test_bare_integer_means_minutes(self):
        self.assertEqual(parse_duration_pl("90"), 90 * 60)

    def test_hours_unit(self):
        self.assertEqual(parse_duration_pl("3h"), 3 * 3600)

    def test_combined_units_with_spaces(self):
        self.assertEqual(parse_duration_pl("1d 2h 30m"), 86400 + 7200 + 1800)

    def test_combined_units_without_spaces(self):
        self.assertEqual(parse_duration_pl("1h30m"), 5400)

    def test_seconds_unit(self):
        self.assertEqual(parse_duration_pl("30s"), 30)

    def test_polish_words(self):
        self.assertEqual(parse_duration_pl("2 godziny"), 7200)
        self.assertEqual(parse_duration_pl("10 minut"), 600)
        self.assertEqual(parse_duration_pl("1 dzień"), 86400)
        self.assertEqual(parse_duration_pl("45 sekund"), 45)

    def test_zero_bare_integer(self):
        self.assertEqual(parse_duration_pl("0"), 0)

    def test_invalid_returns_none(self):
        self.assertIsNone(parse_duration_pl("abc"))
        self.assertIsNone(parse_duration_pl(""))
        self.assertIsNone(parse_duration_pl("-5"))
        self.assertIsNone(parse_duration_pl("3x"))


class TestParseWallclockPl(unittest.TestCase):
    # Parser is timezone-naive on purpose: the cog localizes with pytz.
    NOW = datetime(2026, 7, 11, 12, 0)

    def test_future_time_today(self):
        self.assertEqual(
            parse_wallclock_pl("16:00", self.NOW), datetime(2026, 7, 11, 16, 0)
        )

    def test_past_time_rolls_to_tomorrow(self):
        self.assertEqual(
            parse_wallclock_pl("08:00", self.NOW), datetime(2026, 7, 12, 8, 0)
        )

    def test_time_equal_to_now_rolls_to_tomorrow(self):
        self.assertEqual(
            parse_wallclock_pl("12:00", self.NOW), datetime(2026, 7, 12, 12, 0)
        )

    def test_dot_separator(self):
        self.assertEqual(
            parse_wallclock_pl("16.30", self.NOW), datetime(2026, 7, 11, 16, 30)
        )

    def test_full_datetime(self):
        self.assertEqual(
            parse_wallclock_pl("2026-07-12 09:30", self.NOW),
            datetime(2026, 7, 12, 9, 30),
        )

    def test_date_only_means_midnight(self):
        self.assertEqual(
            parse_wallclock_pl("2026-07-12", self.NOW), datetime(2026, 7, 12, 0, 0)
        )

    def test_invalid_returns_none(self):
        self.assertIsNone(parse_wallclock_pl("25:99", self.NOW))
        self.assertIsNone(parse_wallclock_pl("kiedyś", self.NOW))
        self.assertIsNone(parse_wallclock_pl("", self.NOW))


class TestParseDbTimestamp(unittest.TestCase):
    """Postgres JSON trims trailing zeros in fractional seconds; Python 3.10's
    fromisoformat only accepts exactly 3 or 6 digits — the parser must
    normalize (a bad parse would permanently kill a repeating reminder)."""

    def test_no_fraction(self):
        self.assertEqual(
            parse_db_timestamp("2026-07-11T10:00:00+00:00"),
            datetime(2026, 7, 11, 10, 0, 0, tzinfo=timezone.utc),
        )

    def test_trimmed_single_digit_fraction(self):
        self.assertEqual(
            parse_db_timestamp("2026-07-11T10:00:00.5+00:00"),
            datetime(2026, 7, 11, 10, 0, 0, 500000, tzinfo=timezone.utc),
        )

    def test_trimmed_two_digit_fraction(self):
        self.assertEqual(
            parse_db_timestamp("2026-07-11T10:00:00.12+00:00"),
            datetime(2026, 7, 11, 10, 0, 0, 120000, tzinfo=timezone.utc),
        )

    def test_full_six_digit_fraction(self):
        self.assertEqual(
            parse_db_timestamp("2026-07-11T10:00:00.123456+00:00"),
            datetime(2026, 7, 11, 10, 0, 0, 123456, tzinfo=timezone.utc),
        )

    def test_zulu_suffix(self):
        self.assertEqual(
            parse_db_timestamp("2026-07-11T10:00:00Z"),
            datetime(2026, 7, 11, 10, 0, 0, tzinfo=timezone.utc),
        )

    def test_space_separator_and_offset(self):
        result = parse_db_timestamp("2026-07-11 10:00:00.5+02:00")
        self.assertEqual(result.microsecond, 500000)
        self.assertEqual(result.utcoffset().total_seconds(), 7200)


class TestParseProfileTags(unittest.TestCase):
    """/profil tags: `;`-separated, ≤5 tags, ≤30 chars each."""

    def test_basic_split_and_trim(self):
        self.assertEqual(
            parse_profile_tags("Programowanie; Medycyna ;Sport", 5, 30),
            ["Programowanie", "Medycyna", "Sport"],
        )

    def test_empty_pieces_dropped(self):
        self.assertEqual(parse_profile_tags("a;;b; ;c", 5, 30), ["a", "b", "c"])

    def test_empty_string_clears(self):
        self.assertEqual(parse_profile_tags("", 5, 30), [])
        self.assertEqual(parse_profile_tags("  ", 5, 30), [])

    def test_case_insensitive_dedupe_keeps_first(self):
        self.assertEqual(
            parse_profile_tags("Nauka; nauka; NAUKA; sport", 5, 30),
            ["Nauka", "sport"],
        )

    def test_too_many_tags_returns_none(self):
        self.assertIsNone(parse_profile_tags("a;b;c;d;e;f", 5, 30))

    def test_too_long_tag_returns_none(self):
        self.assertIsNone(parse_profile_tags("x" * 31, 5, 30))

    def test_exactly_at_limits_ok(self):
        tags = parse_profile_tags("a;b;c;d;" + "x" * 30, 5, 30)
        self.assertEqual(tags, ["a", "b", "c", "d", "x" * 30])


class TestParseIndexRanges(unittest.TestCase):
    def test_single_index(self):
        self.assertEqual(parse_index_ranges("1", 5), [1])

    def test_comma_list(self):
        self.assertEqual(parse_index_ranges("1,3", 5), [1, 3])

    def test_range(self):
        self.assertEqual(parse_index_ranges("2-5", 5), [2, 3, 4, 5])

    def test_mixed_with_spaces(self):
        self.assertEqual(parse_index_ranges("1, 3-4, 8", 10), [1, 3, 4, 8])

    def test_all_keywords(self):
        self.assertEqual(parse_index_ranges("all", 3), [1, 2, 3])
        self.assertEqual(parse_index_ranges("-", 3), [1, 2, 3])
        self.assertEqual(parse_index_ranges("wszystkie", 3), [1, 2, 3])

    def test_duplicates_deduplicated(self):
        self.assertEqual(parse_index_ranges("1,1,2-3,3", 5), [1, 2, 3])

    def test_out_of_bounds_returns_none(self):
        self.assertIsNone(parse_index_ranges("7", 5))
        self.assertIsNone(parse_index_ranges("0", 5))
        self.assertIsNone(parse_index_ranges("1-9", 5))

    def test_reversed_range_returns_none(self):
        self.assertIsNone(parse_index_ranges("5-2", 5))

    def test_invalid_returns_none(self):
        self.assertIsNone(parse_index_ranges("", 5))
        self.assertIsNone(parse_index_ranges("a,2", 5))
        self.assertIsNone(parse_index_ranges("1..3", 5))


class TestParseMessageLink(unittest.TestCase):
    def test_plain_link(self):
        url = "https://discord.com/channels/428530875085619200/1533494053977456820/1533494103222784060"
        self.assertEqual(
            parse_message_link(url),
            (428530875085619200, 1533494053977456820, 1533494103222784060),
        )

    def test_link_embedded_in_task_text(self):
        text = "zobacz wiadomość https://discord.com/channels/1/2/3 i odpowiedz"
        self.assertEqual(parse_message_link(text), (1, 2, 3))

    def test_subdomain_and_discordapp_variants(self):
        self.assertEqual(
            parse_message_link("https://ptb.discord.com/channels/1/2/3"), (1, 2, 3)
        )
        self.assertEqual(
            parse_message_link("https://discordapp.com/channels/1/2/3"), (1, 2, 3)
        )

    def test_dm_link_returns_none(self):
        self.assertIsNone(
            parse_message_link("https://discord.com/channels/@me/123/456")
        )

    def test_no_link_returns_none(self):
        self.assertIsNone(parse_message_link("napisz coś miłego na kanale"))
        self.assertIsNone(parse_message_link(""))


class TestParseRecordingFilename(unittest.TestCase):
    def test_wav_filename_parses(self):
        got = parse_recording_filename(
            "Lifehackerzy_2026-07-28-06-30-40_warsztaty-lifehackerow_961c1e.wav"
        )
        self.assertEqual(
            got,
            (datetime(2026, 7, 28, 6, 30, 40), "warsztaty-lifehackerow", "961c1e"),
        )

    def test_mp3_filename_parses(self):
        got = parse_recording_filename(
            "Lifehackerzy_2026-07-23-12-34-46_1234-daily-coaching_497188.mp3"
        )
        self.assertEqual(
            got,
            (datetime(2026, 7, 23, 12, 34, 46), "1234-daily-coaching", "497188"),
        )

    def test_legacy_and_sidecar_names_return_none(self):
        for name in (
            "recording_2026-06-22_21-50-06.wav",
            "Lifehackerzy_2026-07-28-06-30-40_warsztaty-lifehackerow_961c1e.wav.diarization.json",
            "notes.txt",
            "",
            None,
        ):
            self.assertIsNone(parse_recording_filename(name), name)


class TestParseDateArg(unittest.TestCase):
    TODAY = date(2026, 8, 18)

    def test_iso_format(self):
        self.assertEqual(parse_date_arg("2026-08-04", today=self.TODAY), date(2026, 8, 4))

    def test_dd_mm_rrrr_format(self):
        self.assertEqual(parse_date_arg("04.08.2026", today=self.TODAY), date(2026, 8, 4))

    def test_dzisiaj(self):
        self.assertEqual(parse_date_arg("dzisiaj", today=self.TODAY), self.TODAY)

    def test_wczoraj(self):
        self.assertEqual(parse_date_arg("wczoraj", today=self.TODAY), date(2026, 8, 17))

    def test_whitespace_and_case_insensitive(self):
        self.assertEqual(parse_date_arg("  DZISIAJ  ", today=self.TODAY), self.TODAY)
        self.assertEqual(parse_date_arg(" Wczoraj ", today=self.TODAY), date(2026, 8, 17))
        self.assertEqual(parse_date_arg("  2026-08-04  ", today=self.TODAY), date(2026, 8, 4))

    def test_garbage_returns_none(self):
        for raw in ("", "nie-data", "2026/08/04", "32.13.2026", None):
            self.assertIsNone(parse_date_arg(raw, today=self.TODAY), raw)


class TestRewriteBareSocialLink(unittest.TestCase):
    """Guards the two ways this helper could misfire on a live server: rewriting
    a host it must not touch (every proxy is a *suffix* of its source, and
    "x.com" is a suffix of netflix.com), and rewriting its own reply forever."""

    # Własny słownik, nie ten z configu: testy sprawdzają FUNKCJĘ, nie bieżące
    # ustawienia. Zostaje tu "x.com" (usunięty z produkcji, bo Discord dokładał
    # dla niego drugi podgląd), bo to najgorszy przypadek dla dopasowania hosta —
    # jest sufiksem netflix.com i phoenix.com. Gdyby ktoś kiedyś przywrócił go w
    # configu, ta ochrona musi już działać.
    HOSTS = {
        "instagram.com": "kkinstagram.com",
        "tiktok.com": "vxtiktok.com",
        "twitter.com": "fxtwitter.com",
        "x.com": "fxtwitter.com",
    }

    def fix(self, text):
        return rewrite_bare_social_link(text, hosts=self.HOSTS)

    def test_instagram_reel_keeps_path_and_query(self):
        self.assertEqual(
            self.fix("https://www.instagram.com/reel/DXxO9DRRfMk/?stkn=c2R4cHVmb2hvZGx2"),
            "https://kkinstagram.com/reel/DXxO9DRRfMk/?stkn=c2R4cHVmb2hvZGx2",
        )

    def test_host_case_insensitive_but_path_case_preserved(self):
        # Instagram ids są wrażliwe na wielkość liter — ścieżki nie wolno ruszać.
        self.assertEqual(
            self.fix("HTTPS://Instagram.COM/reel/DXxO9DRRfMk/"),
            "https://kkinstagram.com/reel/DXxO9DRRfMk/",
        )

    def test_tiktok_and_x_and_twitter(self):
        self.assertEqual(
            self.fix("https://www.tiktok.com/@u/video/7123?is_from_webapp=1"),
            "https://vxtiktok.com/@u/video/7123?is_from_webapp=1",
        )
        self.assertEqual(
            self.fix("http://x.com/nasa/status/123"),
            "https://fxtwitter.com/nasa/status/123",
        )
        self.assertEqual(
            self.fix("https://twitter.com/nasa/status/123"),
            "https://fxtwitter.com/nasa/status/123",
        )

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(
            self.fix("  https://instagram.com/p/ABC/  "),
            "https://kkinstagram.com/p/ABC/",
        )

    def test_suffix_collision_hosts_not_matched(self):
        # Regresja na pułapkę "x.com": jako fragment wzorca złapałby te hosty.
        for raw in (
            "https://netflix.com/watch/81234",
            "https://phoenix.com/kontakt",
            "https://linux.com/news",
            "https://instagram.com@evil.example/reel/ABC/",
        ):
            self.assertIsNone(self.fix(raw), raw)

    def test_already_fixed_link_not_rewritten(self):
        # Bez tego bot przepisywałby własną odpowiedź w kółko.
        for raw in (
            "https://kkinstagram.com/reel/ABC/",
            "https://www.kkinstagram.com/reel/ABC/",
            "https://vxtiktok.com/@u/video/7",
            "https://fxtwitter.com/nasa/status/1",
        ):
            self.assertIsNone(self.fix(raw), raw)

    def test_target_hosts_are_never_source_hosts(self):
        # Strukturalna gwarancja braku pętli. Sprawdzana i na fixture, i na
        # PRAWDZIWYM configu — to drugie łapie literówkę w EMBED_FIX_HOSTS,
        # przez którą bot przepisywałby własną odpowiedź w kółko.
        for hosts in (self.HOSTS, EMBED_FIX_HOSTS):
            self.assertTrue(set(hosts.values()).isdisjoint(hosts), hosts)

    def test_production_config_is_sane(self):
        # Klucze muszą być małymi literami i bez "www." — parser normalizuje
        # host do tej postaci przed lookupem, więc inny zapis nigdy nie trafi.
        for src, dst in EMBED_FIX_HOSTS.items():
            self.assertEqual(src, src.lower(), src)
            self.assertFalse(src.startswith("www."), src)
            self.assertTrue(dst and "/" not in dst, dst)

    def test_angle_brackets_and_spoiler_return_none(self):
        # Autor świadomie wyłączył podgląd — nie wtrącamy się.
        for raw in (
            "<https://instagram.com/reel/ABC/>",
            "||https://instagram.com/reel/ABC/||",
            "`https://instagram.com/reel/ABC/`",
            "[opis](https://instagram.com/reel/ABC/)",
        ):
            self.assertIsNone(self.fix(raw), raw)

    def test_link_must_be_the_whole_message(self):
        for raw in (
            "zobacz https://instagram.com/reel/ABC/",
            "https://instagram.com/reel/ABC/ mocne",
            "https://instagram.com/p/A/ https://instagram.com/p/B/",
        ):
            self.assertIsNone(self.fix(raw), raw)

    def test_domain_root_returns_none(self):
        for raw in ("https://instagram.com", "https://instagram.com/", "https://x.com/"):
            self.assertIsNone(self.fix(raw), raw)

    def test_garbage_returns_none(self):
        for raw in ("", "   ", None, "instagram.com/reel/ABC/", "nie link"):
            self.assertIsNone(self.fix(raw), raw)


if __name__ == "__main__":
    unittest.main()
