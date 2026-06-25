#!/usr/bin/env python3
"""One-off backup of a Discord channel's recent messages (+ its threads).

Reuses the bot's own token (private.py) but talks to Discord over **REST only** —
it calls ``client.login()`` and the HTTP history paginator, never ``connect()``/
``run()``. So it opens no gateway session and cannot disturb the live systemd bot.

Usage (from the repo root):
    python3 scripts/backup_channel.py            # full backup (writes files)
    python3 scripts/backup_channel.py --count    # dry run: only print totals

Defaults: channel 1128649406640558110, last 4 months. Output goes to
``backups/<channel_id>_<YYYY-MM-DD>/`` (gitignored).
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

# Run from anywhere: make the repo root importable so `private`/`discord` resolve.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import discord  # noqa: E402
from private import DISCORD_TOKEN  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    WARSAW = ZoneInfo("Europe/Warsaw")
except Exception:  # pragma: no cover
    WARSAW = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backup")

CHANNEL_ID = 1128649406640558110
MONTHS_BACK = 4


def _fmt_local(dt: datetime) -> str:
    """UTC-aware datetime -> 'YYYY-MM-DD HH:MM' in Europe/Warsaw."""
    if WARSAW:
        dt = dt.astimezone(WARSAW)
    return dt.strftime("%Y-%m-%d %H:%M")


def _msg_to_dict(m: discord.Message) -> dict:
    return {
        "id": str(m.id),
        "created_at": m.created_at.isoformat(),
        "edited_at": m.edited_at.isoformat() if m.edited_at else None,
        "author": {
            "id": str(m.author.id),
            "name": m.author.name,
            "display_name": getattr(m.author, "display_name", m.author.name),
            "bot": m.author.bot,
        },
        "content": m.content,
        "attachments": [
            {
                "id": str(a.id),
                "filename": a.filename,
                "content_type": a.content_type,
                "size": a.size,
                "url": a.url,
                "local_path": None,  # filled in after download
            }
            for a in m.attachments
        ],
        "embeds": [e.to_dict() for e in m.embeds],
        "reactions": [{"emoji": str(r.emoji), "count": r.count} for r in m.reactions],
        "reference": str(m.reference.message_id) if (m.reference and m.reference.message_id) else None,
        "pinned": m.pinned,
        "type": str(m.type),
    }


async def _collect(channel, after, count_only):
    """Page a channel/thread's history; return (records, attachment_jobs).

    Each attachment job is ``(attachment, record_attachment_dict)``; the actual
    download path is decided later (when the output dir exists).
    """
    records = []
    attach_jobs = []
    async for m in channel.history(limit=None, after=after, oldest_first=True):
        if count_only:
            records.append(None)  # only the count matters
            attach_jobs.extend([None] * len(m.attachments))
            continue
        rec = _msg_to_dict(m)
        for a, arec in zip(m.attachments, rec["attachments"]):
            attach_jobs.append((a, arec))
        records.append(rec)
    return records, attach_jobs


async def _gather_threads(channel):
    """All threads under a text channel: active + archived (public & private)."""
    threads = {}  # id -> thread (dedupe)
    for t in getattr(channel, "threads", []):
        threads[t.id] = t
    for kind, kwargs in (("public", {}), ("private", {"private": True})):
        try:
            async for t in channel.archived_threads(limit=None, **kwargs):
                threads.setdefault(t.id, t)
        except (discord.Forbidden, discord.HTTPException, AttributeError) as e:
            log.warning("Skipping %s archived threads (%s): %s", kind, type(e).__name__, e)
    return list(threads.values())


async def run(count_only: bool):
    cutoff = datetime.now(timezone.utc) - timedelta(days=MONTHS_BACK * 30)
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    await client.login(DISCORD_TOKEN)  # HTTP auth only; no gateway

    try:
        channel = await client.fetch_channel(CHANNEL_ID)
        ch_name = getattr(channel, "name", str(CHANNEL_ID))
        log.info("Channel: #%s (%s)", ch_name, CHANNEL_ID)
        log.info("Range: after %s (last %d months)", cutoff.isoformat(), MONTHS_BACK)

        main_recs, main_jobs = await _collect(channel, cutoff, count_only)
        log.info("Main channel: %d messages, %d attachments", len(main_recs), len(main_jobs))

        threads = await _gather_threads(channel)
        log.info("Found %d thread(s)", len(threads))
        thread_blocks = []
        total_thread_msgs = total_thread_attach = 0
        for t in threads:
            recs, jobs = await _collect(t, cutoff, count_only)
            total_thread_msgs += len(recs)
            total_thread_attach += len(jobs)
            thread_blocks.append((t, recs, jobs))
            log.info("  thread '%s': %d messages, %d attachments", getattr(t, "name", t.id), len(recs), len(jobs))

        total_msgs = len(main_recs) + total_thread_msgs
        total_attach = len(main_jobs) + total_thread_attach
        log.info("TOTAL: %d messages, %d attachments across channel + %d threads",
                 total_msgs, total_attach, len(threads))

        if count_only:
            print(f"\nDRY RUN — would back up:\n"
                  f"  channel #{ch_name}: {len(main_recs)} messages, {len(main_jobs)} attachments\n"
                  f"  {len(threads)} threads: {total_thread_msgs} messages, {total_thread_attach} attachments\n"
                  f"  TOTAL: {total_msgs} messages, {total_attach} attachments")
            return

        # ---- write output ----
        today = datetime.now(WARSAW) if WARSAW else datetime.now()
        out_dir = os.path.join(REPO_ROOT, "backups", f"{CHANNEL_ID}_{today.strftime('%Y-%m-%d')}")
        attach_dir = os.path.join(out_dir, "attachments")
        os.makedirs(attach_dir, exist_ok=True)

        # Download attachments. The attachment id (a global snowflake) keeps
        # filenames unique even when two messages share an attachment name.
        async def download_all(jobs):
            for job in jobs:
                if job is None:
                    continue
                a, arec = job
                safe = f"{arec['id']}_{arec['filename']}".replace("/", "_")
                dest = os.path.join(attach_dir, safe)
                try:
                    await a.save(dest)
                    arec["local_path"] = os.path.relpath(dest, out_dir)
                except Exception as e:
                    log.warning("Attachment download failed (%s): %s", arec["filename"], e)
                    arec["local_path"] = None

        await download_all(main_jobs)
        for _t, _recs, jobs in thread_blocks:
            await download_all(jobs)
        all_jobs = main_jobs + [x for _, _, js in thread_blocks for x in js]
        downloaded = sum(1 for j in all_jobs if j and j[1]["local_path"])

        doc = {
            "channel": {"id": str(CHANNEL_ID), "name": ch_name},
            "range": {"after": cutoff.isoformat(), "generated_at": datetime.now(timezone.utc).isoformat(),
                      "months_back": MONTHS_BACK},
            "messages": main_recs,
            "threads": [
                {"thread": {"id": str(t.id), "name": getattr(t, "name", str(t.id))}, "messages": recs}
                for t, recs, _ in thread_blocks
            ],
        }
        with open(os.path.join(out_dir, "messages.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)

        _write_markdown(os.path.join(out_dir, "messages.md"), ch_name, cutoff, main_recs, thread_blocks)

        with open(os.path.join(out_dir, "README.txt"), "w", encoding="utf-8") as f:
            f.write(
                f"Backup of #{ch_name} ({CHANNEL_ID})\n"
                f"Generated: {datetime.now(timezone.utc).isoformat()}\n"
                f"Range: messages after {cutoff.isoformat()} (last {MONTHS_BACK} months)\n\n"
                f"Main channel messages: {len(main_recs)}\n"
                f"Threads: {len(threads)} ({total_thread_msgs} messages)\n"
                f"Total messages: {total_msgs}\n"
                f"Attachments downloaded: {downloaded}/{total_attach}\n"
            )
        log.info("DONE -> %s  (%d messages, %d/%d attachments)",
                 out_dir, total_msgs, downloaded, total_attach)
        print(f"\nBackup written to: {out_dir}")
    finally:
        await client.close()


def _write_markdown(path, ch_name, cutoff, main_recs, thread_blocks):
    def render(records, title=None, level=1):
        lines = []
        if title:
            lines.append(f"\n{'#' * level} {title}\n")
        for r in records:
            who = r["author"]["display_name"]
            ts = _fmt_local(datetime.fromisoformat(r["created_at"]))
            body = r["content"] or ""
            lines.append(f"**{ts} — {who}:** {body}")
            if r["reference"]:
                lines.append(f"  ↳ (odpowiedź na {r['reference']})")
            for a in r["attachments"]:
                where = a["local_path"] or a["url"]
                lines.append(f"  [załącznik: {a['filename']} → {where}]")
            if r["reactions"]:
                reacts = " ".join(f"{rc['emoji']}×{rc['count']}" for rc in r["reactions"])
                lines.append(f"  ({reacts})")
            lines.append("")  # blank line between messages
        return lines

    out = [f"# Backup #{ch_name}",
           f"_Zakres: wiadomości po {_fmt_local(cutoff)} (ostatnie {MONTHS_BACK} miesiące)_\n",
           "## Kanał główny\n"]
    out += render(main_recs)
    for t, recs, _ in thread_blocks:
        if recs:
            out += render(recs, title=f"Wątek: {getattr(t, 'name', t.id)}", level=2)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Back up a Discord channel's recent messages.")
    ap.add_argument("--count", action="store_true", help="dry run: only print totals, write nothing")
    args = ap.parse_args()
    asyncio.run(run(count_only=args.count))
