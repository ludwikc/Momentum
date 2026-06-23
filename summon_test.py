"""Unit tests for the pure summoning helpers (no discord/openai imports)."""
from summon import build_summon_prompt, is_param_compat_error, is_summon


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


def test_compose_excludes_other_bots_from_participants_but_keeps_in_transcript():
    window = [
        {"author_id": 1, "display_name": "Tomek", "is_bot": False, "content": "cześć"},
        {"author_id": 500, "display_name": "InnyBot", "is_bot": True, "content": "reklama"},
    ]
    result = build_summon_prompt(window, bot_user_id=999)
    assert "InnyBot = " not in result          # other bots never become pingable participants
    assert "InnyBot: reklama" in result        # but their messages stay in the window
    assert result.split("\n\n")[0] == f"{_HEADER}\nTomek = <@1>"


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
