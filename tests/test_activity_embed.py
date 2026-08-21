"""Unit tests for activity_embed — the unified 'Aktywność' progress card.

Covers the hero + 2-column-grid layout: hero elevation per event, the
invisible-spacer trick that forces two columns, de-duplication between hero and
grid, zero-row omission, and graceful fallback when the extended stats RPC has
not populated Deep Work / Daily Coaching yet.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from activity_embed import (  # noqa: E402
    build_activity_embed,
    build_progress_embed,
    format_duration_pl,
)

_ZW = "​"
_DIVIDER = "─" * 15


class _Avatar:
    url = "http://example.test/avatar.png"


class _User:
    avatar = _Avatar()
    default_avatar = _Avatar()


def _fields(embed):
    return [(f.name, f.value, f.inline) for f in embed.fields]


def _real_tiles(embed):
    """Fields that are neither the divider nor an invisible spacer."""
    return [
        (n, v) for n, v, _ in _fields(embed)
        if not (n == _ZW and v in (_ZW, _DIVIDER))
    ]


def _spacers(embed):
    return [(n, v, inline) for n, v, inline in _fields(embed) if n == _ZW]


# --- duration formatting -------------------------------------------------

def test_format_duration_pl_plurals():
    assert format_duration_pl(0) == "0 minut"
    assert format_duration_pl(60) == "1 minuta"
    assert format_duration_pl(3 * 60) == "3 minuty"
    assert format_duration_pl(3600) == "1 godzina"
    assert format_duration_pl(2 * 3600) == "2 godziny"
    assert format_duration_pl(5 * 3600 + 30 * 60) == "5 godzin i 30 minut"
    # negatives clamp to zero, not crash
    assert format_duration_pl(-100) == "0 minut"


# --- headline / description ---------------------------------------------

def test_headline_goes_to_bold_description():
    e = build_progress_embed(_User(), "To 3 sukces w tym miesiącu!", {})
    assert e.description == "**To 3 sukces w tym miesiącu!**"
    assert e.title == "Aktywność"


def test_empty_headline_leaves_no_description():
    e = build_progress_embed(_User(), "", {})
    assert e.description in (None, "")


# --- hero: deep work -----------------------------------------------------

def test_deep_work_hero_two_tiles_and_removed_from_grid():
    stats = {
        "deep_work_seconds": 5 * 3600 + 30 * 60,
        "total_deep_work": 22,
        "total_trening": 12,
        "total_medytacja": 8,
    }
    e = build_progress_embed(_User(), "To 22 sesja Deep Work!", stats,
                             hero_key="deep_work")
    tiles = _real_tiles(e)
    assert ("⏱️ Łączny czas", "**5 godzin i 30 minut**") in tiles
    assert ("📈 Sesje ogółem", "**22**") in tiles
    # Deep Work must NOT reappear in the grid.
    assert not any(name.startswith("⚓️") for name, _ in tiles)
    # A divider separates hero from grid.
    assert (_ZW, _DIVIDER, False) in _fields(e)
    # The activities still show in the grid.
    assert ("💪 Trening", "**12**") in tiles
    assert ("🧘 Medytacja", "**8**") in tiles


def test_deep_work_hero_falls_back_when_no_data():
    # Extended RPC not applied → no deep-work stats. No hero, no divider, no crash.
    stats = {"total_trening": 4}
    e = build_progress_embed(_User(), "To 1 sesja Deep Work!", stats,
                             hero_key="deep_work")
    tiles = _real_tiles(e)
    assert tiles == [("💪 Trening", "**4**")]
    assert not any(v == _DIVIDER for _, v, _ in _fields(e))


# --- hero: activity ------------------------------------------------------

def test_activity_hero_elevates_and_dedupes():
    stats = {"total_medytacja": 8, "total_trening": 12, "coins": 320}
    e = build_progress_embed(_User(), "🔥 To 8 medytacja!", stats,
                             hero_key="medytacja")
    tiles = _real_tiles(e)
    # medytacja is the hero and appears exactly once (as the hero tile).
    med = [t for t in tiles if t[0] == "🧘 Medytacja"]
    assert med == [("🧘 Medytacja", "**8**")]
    # grid keeps the rest
    assert ("💪 Trening", "**12**") in tiles
    assert ("🪙 Monety", "**320**") in tiles


def test_build_activity_embed_sets_hero_and_streak_headline():
    e = build_activity_embed(
        _User(), "medytacja",
        {"streak_count": 8, "consecutive_count": 5},
        {"total_medytacja": 8, "total_trening": 3},
    )
    assert e.description == "**🔥 To 8 medytacja w tym miesiącu! (5 z rzędu!)**"
    med = [t for t in _real_tiles(e) if t[0] == "🧘 Medytacja"]
    assert med == [("🧘 Medytacja", "**8**")]


def test_no_streak_suffix_when_consecutive_small():
    e = build_activity_embed(
        _User(), "trening",
        {"streak_count": 2, "consecutive_count": 2},
        {"total_trening": 2},
    )
    assert e.description == "**🔥 To 2 trening w tym miesiącu!**"


# --- grid: 2-column forcing ---------------------------------------------

def test_grid_forces_two_columns_with_spacers():
    # Four grid tiles, no hero → two full rows, each closed by one spacer.
    stats = {
        "total_trening": 1, "total_medytacja": 2,
        "total_sukces": 3, "total_dziennik": 4,
    }
    e = build_progress_embed(_User(), "cześć", stats)
    tiles = _real_tiles(e)
    assert len(tiles) == 4
    spacers = _spacers(e)
    # floor(4/2) = 2 invisible inline spacers, no divider (no hero).
    assert len(spacers) == 2
    assert all(inline and v == _ZW for _, v, inline in spacers)
    assert not any(v == _DIVIDER for _, v, _ in _fields(e))


def test_grid_odd_tile_has_no_trailing_spacer():
    stats = {"total_trening": 1, "total_medytacja": 2, "total_sukces": 3}
    e = build_progress_embed(_User(), "cześć", stats)
    assert len(_real_tiles(e)) == 3
    assert len(_spacers(e)) == 1  # floor(3/2)


# --- zero-row omission ---------------------------------------------------

def test_zero_stats_are_omitted():
    stats = {"total_trening": 0, "total_medytacja": 5, "coins": 0}
    e = build_progress_embed(_User(), "cześć", stats)
    tiles = _real_tiles(e)
    assert tiles == [("🧘 Medytacja", "**5**")]


def test_none_stats_yields_headline_only():
    e = build_progress_embed(_User(), "cześć", None)
    assert _real_tiles(e) == []
    assert e.description == "**cześć**"


# --- unknown / no hero key ----------------------------------------------

def test_unknown_hero_key_no_hero_no_divider():
    stats = {"total_trening": 12, "total_deep_work": 5, "deep_work_seconds": 3600}
    e = build_progress_embed(_User(), "cześć", stats, hero_key="nieznane")
    tiles = _real_tiles(e)
    # Everything shows in the grid, Deep Work included, no divider.
    assert ("💪 Trening", "**12**") in tiles
    assert any(name.startswith("⚓️") for name, _ in tiles)
    assert not any(v == _DIVIDER for _, v, _ in _fields(e))


def test_daily_coaching_hero():
    stats = {"total_daily_coaching": 4, "total_trening": 12}
    e = build_progress_embed(_User(), "To 4 Daily Coaching!", stats,
                             hero_key="daily_coaching")
    tiles = _real_tiles(e)
    dc = [t for t in tiles if t[0] == "🔢 Daily Coaching"]
    assert dc == [("🔢 Daily Coaching", "**4**")]  # once, as hero
    assert ("💪 Trening", "**12**") in tiles


def test_field_count_stays_within_discord_limit():
    # Worst-ish case: hero + every grid row populated.
    stats = {
        "deep_work_seconds": 3600, "total_deep_work": 22,
        "total_trening": 1, "total_medytacja": 2, "total_sukces": 3,
        "total_dziennik": 4, "total_daily_coaching": 5,
        "voice_seconds_total": 3600, "tasks_done_total": 6, "coins": 7,
    }
    e = build_progress_embed(_User(), "cześć", stats, hero_key="deep_work")
    assert len(e.fields) <= 25
