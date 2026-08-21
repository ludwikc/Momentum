# transcripts.py
# Local store of diarized meeting transcripts + read helpers.
#
# The voice recorder writes one Markdown file per recorded call under transcripts/
# (gitignored). Momentum (cogs/przywolanie.py) reads them via OpenAI tool-calls so it
# can answer questions like "co powiedział Jakub na wczorajszym spotkaniu".
#
# Each file is YAML-ish frontmatter + the diarized body:
#
#     ---
#     data: 2026-06-24 19:30
#     kanal: ogólny
#     uczestnicy: Jakub, Ada, Bartek
#     id: 2026-06-24_19-30_ogolny_a1b2c3
#     ---
#
#     **Jakub:** ...
#     **Ada:** ...
#
# Pure-ish: only the stdlib + filesystem, no discord/openai, so the parsing and
# speaker-filtering logic stays unit-testable (same split as summon.py/transcribe.py).

import logging
import os
import re
from datetime import date, datetime
from typing import Optional

from parsers import parse_recording_filename

logger = logging.getLogger("momentum_bot.transcripts")

TRANSCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcripts")

_SPEAKER_RE = re.compile(r"^\*\*(.+?):\*\*", re.MULTILINE)
_FILENAME_OK = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    return _FILENAME_OK.sub("-", (name or "kanal").lower()).strip("-") or "kanal"


def extract_speakers(body: str) -> list[str]:
    """Distinct speaker labels from a diarized body, in first-appearance order."""
    seen: list[str] = []
    for name in _SPEAKER_RE.findall(body or ""):
        name = name.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def save_transcript(text: str, *, started: datetime, channel_name: str, rec_id: str) -> Optional[str]:
    """Persist a transcript to transcripts/ with metadata. Returns the path (or None).

    Best-effort: never raises into the recording pipeline — a failed save just means
    Momentum can't recall this particular meeting later.
    """
    if not text or not text.strip():
        return None
    try:
        os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
        stem = f"{started.strftime('%Y-%m-%d_%H-%M')}_{_slug(channel_name)}_{rec_id}"
        path = os.path.join(TRANSCRIPTS_DIR, stem + ".md")
        speakers = extract_speakers(text)
        header = (
            "---\n"
            f"data: {started.strftime('%Y-%m-%d %H:%M')}\n"
            f"kanal: {(channel_name or '?').strip()}\n"
            f"uczestnicy: {', '.join(speakers) if speakers else '(nieznani)'}\n"
            f"id: {stem}\n"
            "---\n\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + text.strip() + "\n")
        logger.info("Transcript saved: %s (%d speakers)", path, len(speakers))
        return path
    except Exception as e:
        logger.error("Failed to save transcript for %s: %s", rec_id, e)
        return None


def _parse(path: str) -> dict:
    """Read a transcript file into {meta..., 'body': str}. Tolerates a missing header."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    meta: dict = {}
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = parts[2].lstrip("\n")
    meta["body"] = body
    return meta


def list_transcripts(within_days: Optional[int] = None, *, today: Optional[date] = None) -> list[dict]:
    """List saved meetings newest-first as {id, data, kanal, uczestnicy[]}.

    `within_days` (relative to `today`, default the system date) drops older meetings.
    """
    if not os.path.isdir(TRANSCRIPTS_DIR):
        return []
    today = today or datetime.now().date()
    out: list[dict] = []
    for fname in os.listdir(TRANSCRIPTS_DIR):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(TRANSCRIPTS_DIR, fname)
        try:
            meta = _parse(path)
        except Exception as e:
            logger.warning("Skipping unreadable transcript %s: %s", fname, e)
            continue
        data_str = meta.get("data", "")
        dt = _datetime_of(data_str) or _datetime_of(fname)
        d = dt.date() if dt else None
        if within_days is not None and d is not None and (today - d).days > within_days:
            continue
        out.append({
            "id": meta.get("id") or fname[:-3],
            "data": data_str or fname[:10],
            "kanal": meta.get("kanal", "?"),
            "uczestnicy": [p.strip() for p in meta.get("uczestnicy", "").split(",") if p.strip()],
            "_sort": dt or datetime.min,
        })
    # Full datetime (minute precision), id as deterministic tiebreak — two
    # same-day meetings previously tied on the date and fell to listdir order.
    out.sort(key=lambda m: (m["_sort"], m["id"]), reverse=True)
    for m in out:
        m.pop("_sort", None)
    return out


def _date_of(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _datetime_of(s: str) -> Optional[datetime]:
    """Parse 'YYYY-MM-DD HH:MM' (frontmatter) or 'YYYY-MM-DD_HH-MM' (filename
    stem); date-only strings fall back to midnight via _date_of."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d_%H-%M"):
        try:
            return datetime.strptime((s or "")[:16], fmt)
        except (ValueError, TypeError):
            continue
    d = _date_of(s)
    return datetime(d.year, d.month, d.day) if d else None


def read_transcript(transcript_id: str) -> Optional[str]:
    """Return the diarized body for a transcript id (filename stem), or None."""
    if not transcript_id:
        return None
    safe = os.path.basename(transcript_id)
    if not safe.endswith(".md"):
        safe += ".md"
    path = os.path.join(TRANSCRIPTS_DIR, safe)
    if not os.path.isfile(path):
        return None
    try:
        return _parse(path).get("body", "").strip()
    except Exception as e:
        logger.error("Failed to read transcript %s: %s", transcript_id, e)
        return None


def filter_by_speaker(body: str, name: str) -> str:
    """Return only the turns spoken by `name` (case-insensitive, partial match)."""
    if not body or not name:
        return ""
    needle = name.strip().lower()
    kept = []
    for block in body.split("\n\n"):
        m = re.match(r"^\*\*(.+?):\*\*", block)
        if not m:
            continue
        who = m.group(1).strip().lower()
        if needle in who or who in needle:
            kept.append(block.strip())
    return "\n\n".join(kept)


def find_orphans(recording_names: list[str], transcript_names: list[str]) -> list[str]:
    """WAV recordings that never got a transcript.

    A crash/restart mid-recording (or, historically, the safety-cap self-cancel
    bug) leaves a closed WAV in recordings/ with no .md in transcripts/ — the
    meeting silently drops out of Momentum's memory. The shared rec_id filename
    suffix is the join key; non-recorder names (legacy files, sidecars) are
    ignored. Pure: filename lists in, orphaned .wav names out.
    """
    have = {
        t[:-3].rsplit("_", 1)[-1]
        for t in transcript_names
        if t.endswith(".md")
    }
    out = []
    for r in recording_names:
        if not r.endswith(".wav"):
            continue
        parsed = parse_recording_filename(r)
        if parsed is not None and parsed[2] not in have:
            out.append(r)
    return out
