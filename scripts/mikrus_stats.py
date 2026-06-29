#!/usr/bin/env python3
"""Publish Mikrus server stats (CPU / RAM / disk) as an embed to #〔📊〕mikrus.

Runs from cron every 2h (07:00–23:00 CEST) and posts a single embed signed by
the **Momentum** bot. Reuses the bot's own token (``private.py``) — exactly like
``main.py`` and ``scripts/backup_channel.py`` — so it always posts as Momentum,
never as any other bot configured on the server.

Deliberately stdlib-only: no ``discord.py``, no event loop. Metrics come from
``/proc`` and ``shutil``; the message goes out over a single Discord REST call
(``POST /channels/{id}/messages``) using ``urllib``. That keeps it lightweight
and unable to disturb the live gateway bot.

Usage (from anywhere):
    python3 scripts/mikrus_stats.py

Exit code 0 on a 2xx response, 1 otherwise; a one-line ``OK (200) ...`` or
``ERROR ...`` is printed so the cron log (mikrus_stats.log) stays readable.
"""
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

# Run from anywhere: make the repo root importable so `private` resolves —
# same bootstrap as scripts/backup_channel.py.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from private import DISCORD_TOKEN  # noqa: E402  — Momentum's bot token

# #〔📊〕mikrus on siadlak.VIP
CHANNEL_ID = 1519828429321666791

API_URL = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"

# Embed colour by the most-loaded resource (Discord wants a decimal int).
GREEN = 0x2ECC71   # all resources < 70%
YELLOW = 0xF1C40F  # any resource 70–89%
RED = 0xE74C3C     # any resource >= 90%

BAR_WIDTH = 10
GIB = 1024 ** 3


def cpu_percent(interval: float = 0.5) -> float:
    """Busy CPU % sampled across `interval` seconds from /proc/stat."""
    busy1, total1 = _cpu_sample()
    time.sleep(interval)
    busy2, total2 = _cpu_sample()
    dtotal = total2 - total1
    if dtotal <= 0:
        return 0.0
    return 100.0 * (busy2 - busy1) / dtotal


def _cpu_sample():
    """(busy, total) jiffies from the aggregate `cpu` line of /proc/stat."""
    with open("/proc/stat") as f:
        fields = f.readline().split()  # 'cpu', user, nice, system, idle, iowait, ...
    values = [int(x) for x in fields[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
    total = sum(values)
    return total - idle, total


def mem_stats():
    """(used_percent, used_gib, total_gib) from /proc/meminfo."""
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0])  # value is in kB
    total_kb = info["MemTotal"]
    avail_kb = info.get("MemAvailable", info.get("MemFree", 0))
    used_kb = total_kb - avail_kb
    pct = 100.0 * used_kb / total_kb if total_kb else 0.0
    return pct, used_kb * 1024 / GIB, total_kb * 1024 / GIB


def disk_stats(path: str = "/"):
    """(used_percent, used_gib, total_gib) for the filesystem at `path`."""
    usage = shutil.disk_usage(path)
    pct = 100.0 * usage.used / usage.total if usage.total else 0.0
    return pct, usage.used / GIB, usage.total / GIB


def bar(pct: float) -> str:
    """Text progress bar, e.g. '████░░░░░░'."""
    filled = int(round(pct / 100.0 * BAR_WIDTH))
    filled = max(0, min(BAR_WIDTH, filled))
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def colour_for(max_pct: float) -> int:
    if max_pct >= 90:
        return RED
    if max_pct >= 70:
        return YELLOW
    return GREEN


def build_embed() -> dict:
    cpu = cpu_percent()
    mem_pct, mem_used, mem_total = mem_stats()
    disk_pct, disk_used, disk_total = disk_stats()

    fields = [
        {
            "name": "🧠 CPU",
            "value": f"`{bar(cpu)}` {cpu:.0f}%",
            "inline": False,
        },
        {
            "name": "🧮 RAM",
            "value": f"`{bar(mem_pct)}` {mem_pct:.0f}%  ({mem_used:.1f} / {mem_total:.1f} GiB)",
            "inline": False,
        },
        {
            "name": "💾 Dysk (/)",
            "value": f"`{bar(disk_pct)}` {disk_pct:.0f}%  ({disk_used:.1f} / {disk_total:.1f} GiB)",
            "inline": False,
        },
    ]

    return {
        "title": "📊 Statystyki Mikrusa",
        "color": colour_for(max(cpu, mem_pct, disk_pct)),
        "fields": fields,
        "footer": {"text": "Momentum"},
        # Discord renders this as the embed timestamp in each viewer's locale.
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def post_embed(embed: dict):
    """POST the embed to Discord; return (status_code, body_text)."""
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bot {DISCORD_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "MomentumMikrusStats (https://github.com/ludwikc/Momentum, 1.0)",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def main() -> int:
    embed = build_embed()
    try:
        status, body = post_embed(embed)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        print(f"ERROR HTTP {e.code}: {detail[:500]}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"ERROR network: {e.reason}", file=sys.stderr)
        return 1

    if 200 <= status < 300:
        print(f"OK ({status}) posted to #〔📊〕mikrus ({CHANNEL_ID})")
        return 0
    print(f"ERROR ({status}): {body[:500]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
