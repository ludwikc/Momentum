"""Unit tests for the pure greeting helpers (no discord/openai imports)."""
import re

from greetings import (
    DEEPWORK_HELLOS_FALLBACK,
    build_greeting_prompt,
    decide_greeting_action,
    today_key_warsaw,
)


# --- decide_greeting_action ---------------------------------------------------

def test_decide_full_below_limit():
    for streak in range(5):
        assert decide_greeting_action("full", streak, 5) == "full"


def test_decide_ask_at_and_above_limit():
    assert decide_greeting_action("full", 5, 5) == "ask"
    assert decide_greeting_action("full", 9, 5) == "ask"


def test_decide_plain_ignores_streak():
    assert decide_greeting_action("plain", 0, 5) == "plain"
    assert decide_greeting_action("plain", 99, 5) == "plain"


def test_decide_respects_configurable_limit():
    # A different limit shifts where 'full' flips to 'ask'.
    assert decide_greeting_action("full", 2, 3) == "full"
    assert decide_greeting_action("full", 3, 3) == "ask"


# --- build_greeting_prompt ----------------------------------------------------

def test_prompt_contains_name_weekday_and_time():
    out = build_greeting_prompt("Tomek", "wtorek", "09:30", [])
    assert "Tomek" in out
    assert "wtorek" in out
    assert "09:30" in out


def test_prompt_lists_recent_greetings_in_avoid_section():
    recent = ["Co dziś dowozisz?", "Jaki efekt za 90 minut?"]
    out = build_greeting_prompt("Ala", "piątek", "17:05", recent)
    assert "unikaj" in out.lower()
    for r in recent:
        assert r in out


def test_prompt_without_recent_omits_avoid_section():
    out = build_greeting_prompt("Ala", "piątek", "17:05", [])
    assert "OSTATNIE POWITANIA" not in out


# --- DEEPWORK_HELLOS_FALLBACK -------------------------------------------------

def test_fallback_pool_has_at_least_20_sensible_entries():
    assert len(DEEPWORK_HELLOS_FALLBACK) >= 20
    for text in DEEPWORK_HELLOS_FALLBACK:
        assert text.strip()          # non-empty
        assert len(text) < 200       # sensibly short


def test_fallback_pool_keeps_original_six():
    # The pre-existing greetings must survive the expansion.
    for original in (
        "Nad czym będziesz dziś pracować?",
        "Co jest dzisiaj Twoim MIT (Most Important Task)?",
        "Czas zjeść jakąś 'żabę'? ;)",
    ):
        assert original in DEEPWORK_HELLOS_FALLBACK


# --- today_key_warsaw ---------------------------------------------------------

def test_today_key_format():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", today_key_warsaw())
