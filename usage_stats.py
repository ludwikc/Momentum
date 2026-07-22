"""Pure helpers for Momentum's usage summaries (daily + weekly).

Parses the ``momentum_bot.przywolanie`` lines out of ``bot.log`` and aggregates
them into usage numbers, engaged users, and topics. Kept free of third-party
imports (no discord/openai) so it is unit-testable on its own — same split as
``summon.py``. The runner ``scripts/momentum_usage_summary.py`` does all the
Discord/OpenAI I/O.

Why the log is the source of truth: conversational summons are not persisted to
Supabase (the daily rate limiter lives only in memory), so the log is the only
record of how Momentum is actually being talked to. The richest topical signal
is the ``szukaj_w_bazie`` knowledge-base query the model writes on coaching /
tool-loop turns — a one-line, human-readable description of what was asked.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

# A full log line: "2026-07-22 22:12:58,852 - momentum_bot.przywolanie - INFO - <msg>".
# Only przywolanie lines carry usage signal, so the logger name is matched here.
_LOG_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} - "
    r"momentum_bot\.przywolanie - \w+ - (?P<msg>.*)$"
)
_TS_FMT = "%Y-%m-%d %H:%M:%S"

# Message-body shapes (see cogs/przywolanie.py logger.info calls).
_SUMMON = re.compile(r"^Momentum przywołany na kanale (\d+) przez (\d+)(?P<coach> \(coaching\))?$")
_SLASH_COACH = re.compile(r"^Coaching \(slash\) na kanale (\d+) przez (\d+)$")
_REPLY = re.compile(r"^Momentum odpowiedział w ([\d.]+)s \(coaching=(True|False)\)$")
_SILENCE = re.compile(r"^Model zwrócił ciszę(?: \(przywołanie: (.*)\))?$")
_RATE = re.compile(r"^Dzienny limit \((\d+)\) wyczerpany przez (\d+)")
_TOPIC = re.compile(r"^szukaj_w_bazie: (.*) → (\d+) trafień$")


@dataclass
class Event:
    """One parsed przywolanie log event."""

    ts: datetime
    kind: str  # summon | slash_coaching | reply | silence | rate_limited | topic
    user_id: int | None = None
    channel_id: int | None = None
    coaching: bool = False
    latency: float | None = None
    text: str | None = None  # silence przywołanie text, or topic query


def parse_events(lines) -> list[Event]:
    """Parse przywolanie events out of raw log lines (order preserved).

    Non-matching lines (other loggers, httpx noise, multi-line tracebacks) are
    skipped silently — the log interleaves many sources.
    """
    events: list[Event] = []
    for line in lines:
        m = _LOG_LINE.match(line.rstrip("\n"))
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group("ts"), _TS_FMT)
        except ValueError:
            continue
        msg = m.group("msg")

        if (g := _SUMMON.match(msg)):
            events.append(Event(ts, "summon", user_id=int(g.group(2)),
                                channel_id=int(g.group(1)), coaching=bool(g.group("coach"))))
        elif (g := _SLASH_COACH.match(msg)):
            events.append(Event(ts, "slash_coaching", user_id=int(g.group(2)),
                                channel_id=int(g.group(1)), coaching=True))
        elif (g := _REPLY.match(msg)):
            events.append(Event(ts, "reply", latency=float(g.group(1)),
                                coaching=(g.group(2) == "True")))
        elif (g := _SILENCE.match(msg)):
            events.append(Event(ts, "silence", text=g.group(1)))
        elif (g := _RATE.match(msg)):
            events.append(Event(ts, "rate_limited", user_id=int(g.group(2))))
        elif (g := _TOPIC.match(msg)):
            events.append(Event(ts, "topic", text=g.group(1)))
    return events


@dataclass
class Stats:
    """Aggregated usage over a time window ``[since, until)``."""

    since: datetime
    until: datetime
    summons: int = 0
    coaching_summons: int = 0          # summons flagged (coaching) + /coaching-momentum
    replies: int = 0
    silences: int = 0
    rate_limited: int = 0
    users: Counter = field(default_factory=Counter)      # user_id -> summon count
    channels: Counter = field(default_factory=Counter)   # channel_id -> summon count
    latencies: list[float] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)      # szukaj_w_bazie queries
    silence_texts: list[str] = field(default_factory=list)  # unanswered/terse pings
    rate_limited_users: Counter = field(default_factory=Counter)

    @property
    def unique_users(self) -> int:
        return len(self.users)

    @property
    def unique_channels(self) -> int:
        return len(self.channels)

    @property
    def avg_latency(self) -> float | None:
        return sum(self.latencies) / len(self.latencies) if self.latencies else None

    @property
    def max_latency(self) -> float | None:
        return max(self.latencies) if self.latencies else None

    @property
    def answer_rate(self) -> float | None:
        """Share of summons that got a reply (vs [CISZA]/limit), 0..1."""
        return self.replies / self.summons if self.summons else None


def aggregate(events, since: datetime, until: datetime) -> Stats:
    """Fold events whose timestamp is in ``[since, until)`` into a Stats."""
    s = Stats(since=since, until=until)
    for e in events:
        if not (since <= e.ts < until):
            continue
        if e.kind in ("summon", "slash_coaching"):
            s.summons += 1
            if e.coaching:
                s.coaching_summons += 1
            if e.user_id is not None:
                s.users[e.user_id] += 1
            if e.channel_id is not None:
                s.channels[e.channel_id] += 1
        elif e.kind == "reply":
            s.replies += 1
            if e.latency is not None:
                s.latencies.append(e.latency)
        elif e.kind == "silence":
            s.silences += 1
            if e.text:
                s.silence_texts.append(e.text)
        elif e.kind == "rate_limited":
            s.rate_limited += 1
            if e.user_id is not None:
                s.rate_limited_users[e.user_id] += 1
        elif e.kind == "topic":
            s.topics.append(e.text)
    return s


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def format_daily_embed(stats: Stats, *, max_topics: int = 12, max_users: int = 25) -> dict:
    """Build the admin-facing Discord embed (a raw REST embed dict).

    Mentions in embeds never ping and render as display names, so engaged users
    are listed as ``<@id>`` for a clickable, notification-free roster.
    """
    ar = stats.answer_rate
    lines = [
        f"**Przywołania:** {stats.summons}",
        f"**Odpowiedzi:** {stats.replies}"
        + (f"  ·  skuteczność {ar * 100:.0f}%" if ar is not None else ""),
        f"**Cisza [CISZA]:** {stats.silences}",
        f"**Coaching:** {stats.coaching_summons}",
    ]
    if stats.rate_limited:
        lines.append(f"**Odbite limitem:** {stats.rate_limited}")
    summary_value = "\n".join(lines)

    fields = [{"name": "📈 Aktywność", "value": summary_value, "inline": False}]

    if stats.avg_latency is not None:
        fields.append({
            "name": "⏱️ Czas odpowiedzi",
            "value": f"śr. {stats.avg_latency:.1f}s · max {stats.max_latency:.1f}s",
            "inline": True,
        })

    fields.append({
        "name": f"👥 Zaangażowani ({stats.unique_users})",
        "value": _mentions_block(stats.users, max_users) or "—",
        "inline": True,
    })

    if stats.topics:
        fields.append({
            "name": f"🧭 Tematy z bazy wiedzy ({len(stats.topics)})",
            "value": _bullet_block(stats.topics, max_topics),
            "inline": False,
        })
    if stats.silence_texts:
        fields.append({
            "name": "🔇 Pytania zbyte ciszą",
            "value": _bullet_block(stats.silence_texts, 5),
            "inline": False,
        })
    if stats.rate_limited_users:
        fields.append({
            "name": "🚦 Trafili w dzienny limit",
            "value": _mentions_block(stats.rate_limited_users, 15),
            "inline": False,
        })

    return {
        "title": "🤖 Momentum — dobowe użycie",
        "description": f"Okno: `{_fmt_dt(stats.since)}` → `{_fmt_dt(stats.until)}`",
        "color": 0x5865F2,
        "fields": fields,
        "footer": {"text": "Momentum · raport dla adminów"},
        "timestamp": stats.until.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _mentions_block(counter: Counter, limit: int) -> str:
    items = counter.most_common(limit)
    parts = [f"<@{uid}> ×{n}" if n > 1 else f"<@{uid}>" for uid, n in items]
    extra = len(counter) - len(items)
    if extra > 0:
        parts.append(f"…+{extra}")
    return " ".join(parts)


def _bullet_block(items: list[str], limit: int) -> str:
    """Bulleted, de-duplicated list capped to Discord's ~1024-char field limit."""
    seen: list[str] = []
    for it in items:
        t = _clean_topic(it)
        if t and t not in seen:
            seen.append(t)
    shown = seen[:limit]
    bullets = [f"• {t}" for t in _truncate_each(shown, 180)]
    extra = len(seen) - len(shown)
    if extra > 0:
        bullets.append(f"• …i {extra} więcej")
    block = "\n".join(bullets)
    return block[:1024] if block else "—"


def _clean_topic(raw: str) -> str:
    """Strip surrounding quotes the log preserved around a query/ping text."""
    t = raw.strip()
    if len(t) >= 2 and t[0] in "\"'" and t[-1] == t[0]:
        t = t[1:-1]
    return t.strip()


def _truncate_each(items: list[str], width: int) -> list[str]:
    out = []
    for it in items:
        out.append(it if len(it) <= width else it[: width - 1].rstrip() + "…")
    return out


def build_weekly_digest(stats: Stats) -> str:
    """Compact, factual digest of the week — the material the LLM turns into a
    community-ready post. Numbers plus de-duplicated topic lines; no styling.
    """
    ar = stats.answer_rate
    lines = [
        f"Okres: {_fmt_date(stats.since)} – {_fmt_date(stats.until)}",
        f"Przywołania Momentum: {stats.summons}",
        f"Odpowiedzi udzielone: {stats.replies}"
        + (f" (skuteczność {ar * 100:.0f}%)" if ar is not None else ""),
        f"Sesje/pytania coachingowe: {stats.coaching_summons}",
        f"Zaangażowane osoby: {stats.unique_users}",
        f"Kanały, na których rozmawiano: {stats.unique_channels}",
    ]
    topics = []
    seen = set()
    for t in stats.topics + stats.silence_texts:
        c = _clean_topic(t)
        if c and c not in seen:
            seen.add(c)
            topics.append(c)
    if topics:
        lines.append("")
        lines.append("Tematy, z którymi mierzyła się społeczność:")
        lines.extend(f"- {t}" for t in topics[:40])
    return "\n".join(lines)
