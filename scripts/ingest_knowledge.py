#!/usr/bin/env python3
"""Import the Momentum knowledge base (JSONL) into Supabase with embeddings.

Reads ``data/knowledge.jsonl`` (one object per line:
``{"temat": ..., "odpowiedz": ..., "kategoria": ...}``), embeds each entry with
OpenAI and upserts it into the ``knowledge_base`` table created by
``scripts/knowledge_schema.sql``.

Idempotent: every row carries a ``content_hash`` (sha256 of temat|odpowiedz|kategoria);
entries already present with the same hash are skipped, so re-runs cost no extra
embedding tokens and only new/changed entries are sent.

Run the schema in the Supabase SQL editor FIRST, then (from the repo root):
    python3 scripts/ingest_knowledge.py --limit 50    # trial: first 50 lines
    python3 scripts/ingest_knowledge.py               # full import

Uses the existing OPENAI_API_KEY / SUPABASE_URL / SUPABASE_KEY from .env —
no new dependencies, no SUPABASE_DB_URL.
"""
import argparse
import hashlib
import json
import logging
import os
import sys

# Run from anywhere: make the repo root importable so `db`/`config` resolve.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(REPO_ROOT, ".env"))

import db  # noqa: E402
from config import MOMENTUM_KB_EMBED_DIMS, MOMENTUM_KB_EMBED_MODEL  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("ingest_knowledge")

DEFAULT_PATH = os.path.join(REPO_ROOT, "data", "knowledge.jsonl")
EMBED_BATCH = 100   # inputs per OpenAI embeddings request
UPSERT_BATCH = 200  # rows per Supabase upsert


def _content_hash(temat: str, odpowiedz: str, kategoria: str | None) -> str:
    return hashlib.sha256(
        f"{temat}|{odpowiedz}|{kategoria or ''}".encode("utf-8")
    ).hexdigest()


def _embed_text(temat: str, odpowiedz: str, kategoria: str | None) -> str:
    """The string we actually embed — category prefix helps disambiguate."""
    prefix = f"[{kategoria}] " if kategoria else ""
    return f"{prefix}{temat}\n\n{odpowiedz}"


def load_entries(path: str, limit: int | None) -> list[dict]:
    """Parse JSONL into validated entries with a content_hash. Skips bad lines."""
    entries = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as e:
                logger.warning("Linia %d: niepoprawny JSON (%s) — pomijam", lineno, e)
                continue
            temat = (obj.get("temat") or "").strip()
            odpowiedz = (obj.get("odpowiedz") or "").strip()
            kategoria = (obj.get("kategoria") or "").strip() or None
            if not temat or not odpowiedz:
                logger.warning("Linia %d: brak 'temat' lub 'odpowiedz' — pomijam", lineno)
                continue
            entries.append({
                "temat": temat,
                "odpowiedz": odpowiedz,
                "kategoria": kategoria,
                "content_hash": _content_hash(temat, odpowiedz, kategoria),
            })
            if limit and len(entries) >= limit:
                break
    return entries


def fetch_existing_hashes(supabase) -> set[str]:
    """All content_hash values already in the table (paginated by 1000)."""
    existing: set[str] = set()
    page = 0
    while True:
        start = page * 1000
        result = (
            supabase.table("knowledge_base")
            .select("content_hash")
            .range(start, start + 999)
            .execute()
        )
        rows = result.data or []
        if not rows:
            break
        existing.update(r["content_hash"] for r in rows)
        if len(rows) < 1000:
            break
        page += 1
    return existing


def embed_batch(client, texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(
        model=MOMENTUM_KB_EMBED_MODEL,
        dimensions=MOMENTUM_KB_EMBED_DIMS,
        input=texts,
    )
    # API preserves input order in resp.data.
    return [item.embedding for item in resp.data]


def main() -> int:
    parser = argparse.ArgumentParser(description="Import knowledge base into Supabase.")
    parser.add_argument("--file", default=DEFAULT_PATH, help="ścieżka do JSONL")
    parser.add_argument("--limit", type=int, default=None, help="weź tylko N pierwszych wpisów")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        logger.error("Nie znaleziono pliku: %s", args.file)
        return 1
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("Brak OPENAI_API_KEY w środowisku/.env")
        return 1

    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    supabase = db.get_supabase()

    entries = load_entries(args.file, args.limit)
    logger.info("Wczytano %d poprawnych wpisów z %s", len(entries), args.file)
    if not entries:
        return 0

    existing = fetch_existing_hashes(supabase)
    logger.info("W bazie jest już %d wpisów (po content_hash)", len(existing))

    todo = [e for e in entries if e["content_hash"] not in existing]
    # De-dupe within the file itself (same hash twice → embed once).
    seen, deduped = set(), []
    for e in todo:
        if e["content_hash"] in seen:
            continue
        seen.add(e["content_hash"])
        deduped.append(e)
    todo = deduped
    skipped = len(entries) - len(todo)
    logger.info("Do zaimportowania: %d (pominięto już istniejące/duplikaty: %d)", len(todo), skipped)
    if not todo:
        logger.info("Nic nowego — baza aktualna.")
        return 0

    imported = 0
    for i in range(0, len(todo), EMBED_BATCH):
        chunk = todo[i:i + EMBED_BATCH]
        texts = [_embed_text(e["temat"], e["odpowiedz"], e["kategoria"]) for e in chunk]
        vectors = embed_batch(client, texts)

        rows = []
        for e, vec in zip(chunk, vectors):
            rows.append({
                "temat": e["temat"],
                "odpowiedz": e["odpowiedz"],
                "kategoria": e["kategoria"],
                "content_hash": e["content_hash"],
                "embedding": "[" + ",".join(map(str, vec)) + "]",
            })

        for j in range(0, len(rows), UPSERT_BATCH):
            batch = rows[j:j + UPSERT_BATCH]
            supabase.table("knowledge_base").upsert(
                batch, on_conflict="content_hash"
            ).execute()
            imported += len(batch)
        logger.info("Postęp: %d/%d", imported, len(todo))

    logger.info("Gotowe. Zaimportowano %d nowych wpisów.", imported)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
