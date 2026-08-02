"""Unit tests for the pure summoning helpers (no discord/openai imports)."""
from types import SimpleNamespace

from summon import (
    DISCORD_MESSAGE_LIMIT,
    DailyRateLimiter,
    build_summon_prompt,
    extract_tool_calls,
    format_channel_window,
    is_param_compat_error,
    is_summon,
    offer_allowed,
    repair_mentions,
    split_coaching_offer,
    split_for_discord,
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

_HEADER = (
    "Uczestnicy rozmowy. Gdy zwracasz się do kogoś, wklej DOKŁADNIE jego token w "
    "formacie <@liczba> z tej listy (np. <@123>). NIGDY nie wpisuj imienia w "
    "nawiasach ostrokątnych typu <Imię> — to nie zadziała jako oznaczenie:"
)
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


# --- repair_mentions ----------------------------------------------------------

_RM_WINDOW = [
    {"author_id": 404, "display_name": "Ludwik C. Siadlak 💎", "is_bot": False, "content": "x"},
    {"author_id": 935, "display_name": "JakubP", "is_bot": False, "content": "y"},
    {"author_id": 999, "display_name": "Momentum", "is_bot": True, "content": "z"},
]


def test_repair_mentions_fixes_bracketed_display_name():
    out = repair_mentions("<Ludwik C. Siadlak 💎>, tak: ...", _RM_WINDOW, bot_user_id=999)
    assert out == "<@404>, tak: ..."


def test_repair_mentions_fixes_at_prefixed_name_form():
    out = repair_mentions("hej <@JakubP> zobacz", _RM_WINDOW, bot_user_id=999)
    assert out == "hej <@935> zobacz"


def test_repair_mentions_leaves_correct_tokens_and_prose_untouched():
    # A already-correct token and a bare name in prose must not be rewritten.
    text = "Zgadzam się z <@404>. Ludwik ma rację, JakubP też."
    assert repair_mentions(text, _RM_WINDOW, bot_user_id=999) == text


def test_repair_mentions_ignores_bot_and_empty():
    assert repair_mentions("<Momentum> mówi", _RM_WINDOW, bot_user_id=999) == "<Momentum> mówi"
    assert repair_mentions("", _RM_WINDOW, bot_user_id=999) == ""


# --- split_coaching_offer ------------------------------------------------------

def test_split_coaching_offer_answer_on_next_line():
    assert split_coaching_offer("[COACHING?]\nOdpowiedź tutaj") == (True, "Odpowiedź tutaj")


def test_split_coaching_offer_answer_on_same_line():
    assert split_coaching_offer("[COACHING?] Odpowiedź tutaj") == (True, "Odpowiedź tutaj")


def test_split_coaching_offer_bare_sentinel():
    assert split_coaching_offer("[COACHING?]") == (True, "")


def test_split_coaching_offer_tolerates_leading_whitespace():
    assert split_coaching_offer("  [COACHING?]\nOdpowiedź") == (True, "Odpowiedź")


def test_split_coaching_offer_passthrough_when_absent():
    assert split_coaching_offer("Zwykła odpowiedź bez sentinela") == (
        False,
        "Zwykła odpowiedź bez sentinela",
    )


def test_split_coaching_offer_ignores_sentinel_mid_text():
    text = "Odpowiedź, w środku której ktoś wkleił [COACHING?] przypadkiem."
    assert split_coaching_offer(text) == (False, text)


def test_split_coaching_offer_empty_string():
    assert split_coaching_offer("") == (False, "")


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


# --- split_for_discord ---------------------------------------------------------

def test_split_short_reply_is_single_chunk():
    assert split_for_discord("Krótka odpowiedź.") == ["Krótka odpowiedź."]


def test_split_empty_and_whitespace_yield_no_chunks():
    assert split_for_discord("") == []
    assert split_for_discord("   \n\n  ") == []
    assert split_for_discord(None) == []


def test_split_long_reply_respects_limit_and_loses_nothing():
    paragraphs = [f"Sekcja {i}: " + "treść instrukcji dla społeczności. " * 20 for i in range(12)]
    text = "\n\n".join(paragraphs)
    chunks = split_for_discord(text)
    assert len(chunks) > 1
    assert all(len(c) <= DISCORD_MESSAGE_LIMIT for c in chunks)
    # No content is lost — only whitespace at the split points may differ.
    assert "".join(c.replace("\n", "").replace(" ", "") for c in chunks) == \
        text.replace("\n", "").replace(" ", "")


def test_split_prefers_paragraph_boundaries():
    para = "a" * 1500
    text = f"{para}\n\n{para}"
    assert split_for_discord(text) == [para, para]


def test_split_hard_cuts_unbroken_text():
    text = "x" * 4100
    chunks = split_for_discord(text)
    assert chunks == ["x" * 2000, "x" * 2000, "x" * 100]


def test_split_ignores_boundary_in_first_half_of_window():
    # A lone newline early in the text must not produce a tiny first chunk.
    text = "nagłówek\n" + "y" * 2500
    chunks = split_for_discord(text)
    assert len(chunks[0]) > DISCORD_MESSAGE_LIMIT // 2
    assert all(len(c) <= DISCORD_MESSAGE_LIMIT for c in chunks)


def test_split_custom_limit():
    chunks = split_for_discord("jeden dwa trzy cztery pięć", limit=10)
    assert all(len(c) <= 10 for c in chunks)
    assert " ".join(chunks) == "jeden dwa trzy cztery pięć"


# --- offer_allowed ---------------------------------------------------------------

def test_offer_allowed_when_never_offered():
    assert offer_allowed(None, 100.0, 1800.0) is True


def test_offer_blocked_within_cooldown():
    assert offer_allowed(100.0, 1000.0, 1800.0) is False


def test_offer_allowed_at_and_after_cooldown():
    assert offer_allowed(100.0, 1900.0, 1800.0) is True
    assert offer_allowed(100.0, 5000.0, 1800.0) is True


# --- format_channel_window ----------------------------------------------------

def test_format_window_participants_and_transcript_without_closing():
    window = [
        {"author_id": 1, "display_name": "Ala", "is_bot": False, "content": "hej"},
        {"author_id": 99, "display_name": "Momentum", "is_bot": True, "content": "cześć"},
    ]
    out = format_channel_window(window, 99)
    assert "Ala = <@1>" in out
    assert "Momentum: cześć" in out
    assert "[CISZA]" not in out
    assert "Zostałeś" not in out


def test_format_window_empty_returns_empty_string():
    assert format_channel_window([], 99) == ""


def test_build_summon_prompt_starts_with_formatted_window():
    window = [
        {"author_id": 1, "display_name": "Ala", "is_bot": False, "content": "Momentum?"}
    ]
    out = build_summon_prompt(window, 99)
    assert out.startswith(format_channel_window(window, 99))
    assert "[CISZA]" in out
