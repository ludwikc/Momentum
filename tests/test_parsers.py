import unittest
from datetime import datetime, timezone

from parsers import (
    parse_db_timestamp,
    parse_duration_pl,
    parse_index_ranges,
    parse_profile_tags,
    parse_wallclock_pl,
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


if __name__ == "__main__":
    unittest.main()
