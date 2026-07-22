"""Unit tests for the pure summoning helpers (no discord/openai imports)."""
from types import SimpleNamespace

from summon import (
    DailyRateLimiter,
    build_summon_prompt,
    extract_tool_calls,
    is_param_compat_error,
    is_summon,
)


# --- is_summon ----------------------------------------------------------------

def test_is_summon_matches_name_case_insensitive():
    assert is_summon("Momentum, a jak Ty myślisz?", False) is True
    assert is_summon("MOMENTUM???", False) is True
    assert is_summon("no to momentum buduje się powoli", False) is True


def test_is_summon_true_when_bot_mentioned_regardless_of_text():
    assert is_summon("hej <@404038151565213696> co tam", True) is True


def test_is_summon_ignores_inflected_and_common_forms():
    assert is_summon("w tym momencie się zorientowałem", False) is False
    assert is_summon("brakuje mi momentu na refleksję", False) is False
    assert is_summon("Momencie, pomóż", False) is False


def test_is_summon_requires_whole_word():
    assert is_summon("momentumowy plan", False) is False


def test_is_summon_false_for_ordinary_message():
    assert is_summon("Dzięki za wczorajsze spotkanie!", False) is False


# --- build_summon_prompt ----------------------------------------------------

_HEADER = "Uczestnicy rozmowy (użyj dokładnie tych tokenów, gdy zwracasz się do kogoś):"
_CLOSING = (
    "Zostałeś przywołany w tej rozmowie. Odezwij się zgodnie ze swoją rolą albo, "
    "jeśli to nie była prośba o Twoje zdanie, zwróć dokładnie: [CISZA]"
)
_CLOSING_DIRECT = (
    "Zostałeś WPROST przywołany po imieniu (albo ktoś pisze do Ciebie bezpośrednio) "
    "w tej rozmowie — to jednoznaczna prośba o Twoją uwagę. Odezwij się zgodnie ze "
    "swoją rolą i NIE zwracaj [CISZA] — zawsze się angażujesz. Jeśli pytanie jest "
    "krótkie lub zależy od wcześniejszego kontekstu, oprzyj się na powyższej rozmowie; "
    "a jeśli naprawdę nie wiadomo, o co chodzi, dopytaj zamiast milczeć."
)


def test_compose_single_human_message():
    window = [
        {"author_id": 1, "display_name": "Tomek", "is_bot": False,
         "content": "Momentum, co myślisz?"},
    ]
    assert build_summon_prompt(window, bot_user_id=999) == (
        f"{_HEADER}\n"
        "Tomek = <@1>\n"
        "\n"
        "Tomek: Momentum, co myślisz?\n"
        "\n"
        f"{_CLOSING}"
    )


def test_compose_dedupes_participants_and_labels_bot_as_momentum():
    window = [
        {"author_id": 1, "display_name": "Tomek", "is_bot": False, "content": "mam blokadę"},
        {"author_id": 2, "display_name": "Anna", "is_bot": False, "content": "ja tak samo"},
        {"author_id": 999, "display_name": "Momentum", "is_bot": True, "content": "Słyszę Was"},
        {"author_id": 1, "display_name": "Tomek", "is_bot": False,
         "content": "Momentum, a jak Ty myślisz?"},
    ]
    assert build_summon_prompt(window, bot_user_id=999) == (
        f"{_HEADER}\n"
        "Tomek = <@1>\n"
        "Anna = <@2>\n"
        "\n"
        "Tomek: mam blokadę\n"
        "Anna: ja tak samo\n"
        "Momentum: Słyszę Was\n"
        "Tomek: Momentum, a jak Ty myślisz?\n"
        "\n"
        f"{_CLOSING}"
    )


def test_compose_default_uses_cisza_closing():
    window = [
        {"author_id": 1, "display_name": "Tomek", "is_bot": False, "content": "momentum się buduje"},
    ]
    result = build_summon_prompt(window, bot_user_id=999)
    assert result.endswith(_CLOSING)
    assert "[CISZA]" in result


def test_compose_direct_mention_drops_cisza_and_forces_engagement():
    window = [
        {"author_id": 1, "display_name": "Tomek", "is_bot": False,
         "content": "@Momentum a Ty wiesz?"},
    ]
    result = build_summon_prompt(window, bot_user_id=999, direct_mention=True)
    assert result.endswith(_CLOSING_DIRECT)
    assert "NIE zwracaj [CISZA]" in result
    # The plain "return exactly [CISZA]" escape hatch must be gone.
    assert "zwróć dokładnie: [CISZA]" not in result


def test_compose_excludes_other_bots_from_participants_but_keeps_in_transcript():
    window = [
        {"author_id": 1, "display_name": "Tomek", "is_bot": False, "content": "cześć"},
        {"author_id": 500, "display_name": "InnyBot", "is_bot": True, "content": "reklama"},
    ]
    result = build_summon_prompt(window, bot_user_id=999)
    assert "InnyBot = " not in result          # other bots never become pingable participants
    assert "InnyBot: reklama" in result        # but their messages stay in the window
    assert result.split("\n\n")[0] == f"{_HEADER}\nTomek = <@1>"


# --- DailyRateLimiter ---------------------------------------------------------

def test_rate_limiter_allows_up_to_limit_then_blocks():
    rl = DailyRateLimiter(limit=5)
    assert [rl.allow(1, "2026-06-24") for _ in range(5)] == [True] * 5
    assert rl.allow(1, "2026-06-24") is False
    assert rl.allow(1, "2026-06-24") is False  # stays blocked


def test_rate_limiter_is_per_user():
    rl = DailyRateLimiter(limit=2)
    assert rl.allow(1, "d") and rl.allow(1, "d")
    assert rl.allow(1, "d") is False
    assert rl.allow(2, "d") is True  # a different user has their own bucket


def test_rate_limiter_resets_on_new_day():
    rl = DailyRateLimiter(limit=1)
    assert rl.allow(1, "2026-06-24") is True
    assert rl.allow(1, "2026-06-24") is False
    assert rl.allow(1, "2026-06-25") is True  # new day, fresh allowance


def test_rate_limiter_zero_or_negative_limit_is_unlimited():
    rl = DailyRateLimiter(limit=0)
    assert all(rl.allow(1, "d") for _ in range(100))


# --- is_param_compat_error ----------------------------------------------------

def test_param_compat_error_detects_max_tokens():
    assert is_param_compat_error(
        "Unsupported parameter: 'max_tokens' is not supported with this model. "
        "Use 'max_completion_tokens' instead."
    ) is True


def test_param_compat_error_detects_temperature():
    assert is_param_compat_error(
        "Unsupported value: 'temperature' does not support 0.8 with this model. "
        "Only the default (1) value is supported."
    ) is True


def test_param_compat_error_ignores_unrelated_errors():
    assert is_param_compat_error("Rate limit reached for requests") is False
    assert is_param_compat_error("You exceeded your current quota (insufficient_quota)") is False
    assert is_param_compat_error("Incorrect API key provided") is False
    assert is_param_compat_error("") is False


# --- extract_tool_calls -------------------------------------------------------

def test_extract_tool_calls_returns_function_calls_in_order():
    output = [
        SimpleNamespace(type="reasoning"),
        SimpleNamespace(
            type="function_call",
            call_id="c1",
            name="szukaj_w_bazie",
            arguments='{"pytanie":"jak zacząć"}',
        ),
        SimpleNamespace(type="message", content="ignored"),
        SimpleNamespace(type="function_call", call_id="c2", name="lista_spotkan", arguments=""),
    ]
    assert extract_tool_calls(output) == [
        ("c1", "szukaj_w_bazie", '{"pytanie":"jak zacząć"}'),
        ("c2", "lista_spotkan", ""),
    ]


def test_extract_tool_calls_empty_when_no_function_calls():
    output = [SimpleNamespace(type="message", content="hej"), SimpleNamespace(type="reasoning")]
    assert extract_tool_calls(output) == []
