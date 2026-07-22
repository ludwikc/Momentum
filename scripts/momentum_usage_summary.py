#!/usr/bin/env python3
"""Post a Momentum usage summary to the admin channel.

Two periods:
  * ``--period daily``  — an admin-formatted embed (raw numbers, engaged users,
    topics, health) for the previous 24h. For the admins' eyes.
  * ``--period weekly`` — a community-ready post written in **Ludwik's voice**
    (via OpenAI, grounded in the week's real activity), for the previous 7 days.
    Ready to copy-paste and publish.

Reads the rotated log set (``bot.log`` + ``bot.log-*`` / ``.gz``) so it keeps
working after logrotate runs, and filters events to the requested window. All
pure parsing/aggregation lives in ``usage_stats.py`` (unit-tested); this file is
the thin I/O shell — exactly the split used by ``summon.py`` / ``przywolanie``.

Reuses the bot's own token (``private.py``) so it always posts as **Momentum**,
like ``scripts/mikrus_stats.py`` and ``scripts/backup_channel.py``. The Discord
call is a single REST ``POST /channels/{id}/messages`` over ``urllib`` — no
gateway, no event loop, safe to run from cron alongside the live bot.

Usage:
    python3 scripts/momentum_usage_summary.py --period daily
    python3 scripts/momentum_usage_summary.py --period weekly
    python3 scripts/momentum_usage_summary.py --period daily --dry-run
    python3 scripts/momentum_usage_summary.py --period weekly --days 30   # backfill

Exit code 0 on success, 1 on any post/generation error; prints a one-line
``OK ...`` / ``ERROR ...`` so the cron log stays readable.
"""
import argparse
import glob
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

# Run from anywhere: make the repo root importable so `private`/`config`/
# `usage_stats` resolve — same bootstrap as scripts/mikrus_stats.py.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Load OPENAI_API_KEY (and friends) from .env, exactly like main.py, so the
# weekly narrative works under cron where the shell env is bare. Optional: the
# daily embed and the Discord post itself need only DISCORD_TOKEN (private.py).
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(REPO_ROOT, ".env"))
except ImportError:
    pass

from private import DISCORD_TOKEN  # noqa: E402  — Momentum's bot token
from config import MOMENTUM_USAGE_CHANNEL_ID, MOMENTUM_MODEL  # noqa: E402
from usage_stats import (  # noqa: E402
    aggregate,
    build_weekly_digest,
    format_daily_embed,
    parse_events,
)

LOG_GLOB = os.path.join(REPO_ROOT, "bot.log*")
API_URL = f"https://discord.com/api/v10/channels/{MOMENTUM_USAGE_CHANNEL_ID}/messages"
USER_AGENT = "MomentumUsageSummary (https://github.com/ludwikc/Momentum, 1.0)"
CONTENT_LIMIT = 1900  # Discord hard limit is 2000; leave headroom.

# System prompt for the weekly narrative. Ludwik's voice is intense, second
# person, sovereignty/ownership themed — grounded here so the model doesn't
# drift into generic "bot statistics" copy.
LUDWIK_VOICE = (
    "Jesteś Ludwikiem C. Siadlakiem — założycielem społeczności Lifehackerów. "
    "Piszesz krótkie, mocne, osobiste podsumowanie tygodnia dla społeczności. "
    "Twój styl: bezpośredni zwrot do czytelnika (per 'Ty'), energia, "
    "odpowiedzialność i sprawczość ('jesteś architektem swoich wyników'), "
    "konkret zamiast lania wody, lekko prowokujące pytanie, które popycha do "
    "działania. Bez korporacyjnego żargonu, bez 'raportowania statystyk' — "
    "liczby wplatasz naturalnie jako dowód, że społeczność realnie działa.\n\n"
    "Napisz post (ok. 900–1400 znaków), gotowy do opublikowania tak jak jest:\n"
    "1) mocne otwarcie nawiązujące do tego, co działo się w tym tygodniu,\n"
    "2) 2–4 tematy/wątki, z którymi mierzyli się Lifehackerzy (na podstawie "
    "danych poniżej — uogólnij je po ludzku, nie cytuj surowych zapytań),\n"
    "3) domknięcie: jedno konkretne zaproszenie/pytanie na nadchodzący tydzień.\n"
    "Pisz po polsku. Nie używaj nagłówków markdown ani list punktowanych — "
    "to ma brzmieć jak wpis Ludwika, nie jak raport. Nie wymyślaj faktów "
    "spoza danych."
)


def iter_log_lines(paths):
    """Yield every line across the rotated log set (plain + .gz), oldest-ish
    first. Order within the window does not matter — aggregate() filters by
    timestamp — so a simple sorted glob is enough.
    """
    for path in paths:
        opener = gzip.open if path.endswith(".gz") else open
        try:
            with opener(path, "rt", encoding="utf-8", errors="replace") as f:
                yield from f
        except (OSError, EOFError) as e:
            print(f"WARN could not read {path}: {e}", file=sys.stderr)


def load_stats(since, until):
    paths = sorted(glob.glob(LOG_GLOB))
    events = parse_events(iter_log_lines(paths))
    return aggregate(events, since, until), paths


def generate_weekly_text(stats) -> str:
    """Ask OpenAI to write the week in Ludwik's voice. Falls back to the plain
    digest if the key is missing or the call fails — a summary still gets posted.
    """
    digest = build_weekly_digest(stats)
    if not os.getenv("OPENAI_API_KEY"):
        print("WARN no OPENAI_API_KEY — posting plain digest instead of narrative",
              file=sys.stderr)
        return digest
    try:
        from openai import OpenAI

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        # gpt-5.2 rejects max_tokens/temperature — use the conservative param set
        # directly (same lesson as cogs/przywolanie.py) to avoid a retry round-trip.
        resp = client.chat.completions.create(
            model=MOMENTUM_MODEL,
            messages=[
                {"role": "system", "content": LUDWIK_VOICE},
                {"role": "user", "content":
                    "Dane o użyciu Momentum w tym tygodniu:\n\n" + digest},
            ],
            max_completion_tokens=1200,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or digest
    except Exception as e:  # noqa: BLE001 — never let a summary run die on the LLM
        print(f"WARN weekly narrative failed ({e}) — posting plain digest",
              file=sys.stderr)
        return digest


def _post(payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=data, method="POST",
        headers={
            "Authorization": f"Bot {DISCORD_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def post_embed(embed: dict):
    return _post({"embeds": [embed], "allowed_mentions": {"parse": []}})


def _chunks(text: str, size: int):
    """Split on paragraph/line boundaries so a long weekly post stays readable
    across multiple Discord messages."""
    out, buf = [], ""
    for para in text.split("\n"):
        if len(buf) + len(para) + 1 > size and buf:
            out.append(buf)
            buf = ""
        buf = f"{buf}\n{para}" if buf else para
    if buf:
        out.append(buf)
    return out or [text[:size]]


def post_text(text: str):
    status = 0
    body = ""
    for chunk in _chunks(text, CONTENT_LIMIT):
        status, body = _post({"content": chunk, "allowed_mentions": {"parse": []}})
        if not (200 <= status < 300):
            return status, body
        time.sleep(0.4)  # gentle on the per-channel rate limit for multi-part posts
    return status, body


def main() -> int:
    ap = argparse.ArgumentParser(description="Post a Momentum usage summary.")
    ap.add_argument("--period", choices=("daily", "weekly"), default="daily")
    ap.add_argument("--days", type=float, default=None,
                    help="Override the window length (default 1 for daily, 7 for weekly).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be posted; do not call Discord.")
    args = ap.parse_args()

    until = datetime.now().replace(microsecond=0)
    days = args.days if args.days is not None else (7 if args.period == "weekly" else 1)
    since = until - timedelta(days=days)

    stats, paths = load_stats(since, until)
    print(f"Parsed {len(paths)} log file(s); window {since:%Y-%m-%d %H:%M} → "
          f"{until:%Y-%m-%d %H:%M}: {stats.summons} summons, "
          f"{stats.unique_users} users, {len(stats.topics)} topics")

    if args.period == "daily":
        embed = format_daily_embed(stats)
        if args.dry_run:
            print(json.dumps(embed, ensure_ascii=False, indent=2))
            return 0
        poster = lambda: post_embed(embed)  # noqa: E731
        target = "dobowe (embed)"
    else:
        text = generate_weekly_text(stats)
        if args.dry_run:
            print(text)
            return 0
        poster = lambda: post_text(text)  # noqa: E731
        target = "tygodniowe (Ludwik)"

    try:
        status, body = poster()
    except urllib.error.HTTPError as e:
        print(f"ERROR HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}",
              file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"ERROR network: {e.reason}", file=sys.stderr)
        return 1

    if 200 <= status < 300:
        print(f"OK ({status}) posted {target} to #{MOMENTUM_USAGE_CHANNEL_ID}")
        return 0
    print(f"ERROR ({status}): {body[:500]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
