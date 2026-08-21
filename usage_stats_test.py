"""Unit tests for the pure usage-summary helpers (no discord/openai imports)."""
from datetime import datetime

from usage_stats import (
    aggregate,
    build_weekly_digest,
    format_daily_embed,
    parse_events,
)

P = "momentum_bot.przywolanie"


def _line(ts: str, msg: str, logger: str = P, level: str = "INFO") -> str:
    return f"{ts},000 - {logger} - {level} - {msg}"


# A realistic mixed log slice (interleaved httpx noise + tracebacks are ignored).
SAMPLE = [
    _line("2026-07-20 09:00:00", "Momentum przywołany na kanale 111 przez 501"),
    "2026-07-20 09:00:01,000 - httpx - INFO - HTTP Request: POST ... 200 OK",
    _line("2026-07-20 09:00:06", "Momentum odpowiedział w 6.0s (coaching=False)"),
    _line("2026-07-20 10:00:00", "Momentum przywołany na kanale 111 przez 502 (coaching)"),
    _line("2026-07-20 10:00:02", "szukaj_w_bazie: 'Jak utrzymać fokus pod deadline?' → 3 trafień"),
    _line("2026-07-20 10:00:09", "Momentum odpowiedział w 9.0s (coaching=True)"),
    _line("2026-07-20 11:00:00", "Momentum przywołany na kanale 222 przez 501"),
    _line("2026-07-20 11:00:05", "Model zwrócił ciszę (przywołanie: '@Momentum a Ty wiesz?')"),
    _line("2026-07-20 12:00:00", "Coaching (slash) na kanale 333 przez 503"),
    _line("2026-07-20 12:00:04", "Momentum odpowiedział w 4.0s (coaching=True)"),
    _line("2026-07-20 13:00:00", "Dzienny limit (5) wyczerpany przez 502 — pomijam"),
    "not a log line at all",
]


def _events():
    return parse_events(SAMPLE)


# --- parse_events -------------------------------------------------------------

def test_parse_ignores_non_przywolanie_and_garbage():
    ev = _events()
    # 4 summon-ish (3 summon + 1 slash) + 3 reply + 1 silence + 1 rate + 1 topic = 10
    assert len(ev) == 10
    assert {e.kind for e in ev} == {"summon", "slash_coaching", "reply", "silence", "rate_limited", "topic"}


def test_parse_summon_fields_and_coaching_flag():
    summons = [e for e in _events() if e.kind == "summon"]
    assert (summons[0].user_id, summons[0].channel_id, summons[0].coaching) == (501, 111, False)
    assert summons[1].coaching is True  # the "(coaching)" one


def test_parse_reply_latency_and_topic_text():
    replies = [e for e in _events() if e.kind == "reply"]
    assert [r.latency for r in replies] == [6.0, 9.0, 4.0]
    topic = next(e for e in _events() if e.kind == "topic")
    assert topic.text == "'Jak utrzymać fokus pod deadline?'"


def test_parse_silence_text_extracted():
    sil = next(e for e in _events() if e.kind == "silence")
    assert sil.text == "'@Momentum a Ty wiesz?'"


# --- aggregate ----------------------------------------------------------------

def _full_window():
    return aggregate(_events(), datetime(2026, 7, 20), datetime(2026, 7, 21))


def test_aggregate_counts():
    s = _full_window()
    assert s.summons == 4          # 3 summon + 1 slash coaching
    assert s.coaching_summons == 2  # one "(coaching)" summon + one slash
    assert s.replies == 3
    assert s.silences == 1
    assert s.rate_limited == 1
    assert s.unique_users == 3      # 501, 502, 503
    assert s.unique_channels == 3   # 111, 222, 333
    assert s.users[501] == 2        # summoned twice


def test_aggregate_answer_rate_and_latency():
    s = _full_window()
    assert round(s.answer_rate, 2) == 0.75  # 3 replies / 4 summons
    assert s.avg_latency == (6.0 + 9.0 + 4.0) / 3
    assert s.max_latency == 9.0


def test_aggregate_window_excludes_out_of_range():
    # A one-hour window catches only the 09:00 summon + its reply.
    s = aggregate(_events(), datetime(2026, 7, 20, 9), datetime(2026, 7, 20, 10))
    assert s.summons == 1 and s.replies == 1 and s.coaching_summons == 0


def test_aggregate_until_is_exclusive():
    s = aggregate(_events(), datetime(2026, 7, 20), datetime(2026, 7, 20, 9))
    assert s.summons == 0  # the 09:00:00 event is excluded at the boundary


# --- formatting ---------------------------------------------------------------

def test_daily_embed_shape_and_content():
    embed = format_daily_embed(_full_window())
    assert embed["title"].startswith("🤖 Momentum")
    names = {f["name"] for f in embed["fields"]}
    assert any("Aktywność" in n for n in names)
    assert any("Zaangażowani (3)" in n for n in names)
    assert any("Tematy" in n for n in names)
    activity = next(f["value"] for f in embed["fields"] if "Aktywność" in f["name"])
    assert "Przywołania:** 4" in activity
    assert "skuteczność 75%" in activity


def test_daily_embed_topic_quotes_stripped():
    topics_field = next(
        f["value"] for f in format_daily_embed(_full_window())["fields"] if "Tematy" in f["name"]
    )
    assert "Jak utrzymać fokus pod deadline?" in topics_field
    assert "'" not in topics_field  # surrounding quotes cleaned


def test_weekly_digest_is_plain_and_lists_topics():
    digest = build_weekly_digest(_full_window())
    assert "Przywołania Momentum: 4" in digest
    assert "Zaangażowane osoby: 3" in digest
    assert "Jak utrzymać fokus pod deadline?" in digest
    assert "@Momentum a Ty wiesz?" in digest  # silence texts fold into topics too


def test_empty_window_produces_valid_embed():
    s = aggregate([], datetime(2026, 7, 20), datetime(2026, 7, 21))
    embed = format_daily_embed(s)
    assert embed["fields"]  # never crashes on zero activity
    assert s.answer_rate is None
