#!/usr/bin/env python3
"""One-time backfill: upload existing local transcripts/*.md to Google Drive.

Historically the Drive copy of a transcript was a bare `.txt` (or, for older
meetings, never uploaded at all). Since 2026-08 the recording pipeline uploads
the full transcript markdown as `<audio-stem>-transcript.md` next to the mp3
(see cogs/voicerecord.py::_upload_transcript, transcripts.render_document).
This script closes the gap for meetings recorded before that change.

For each local transcripts/*.md file:
  1. Derive `rec_id` the same way transcripts.find_orphans does — the last
     "_"-separated token of the filename stem.
  2. `gdrive.find_files(rec_id)` — the rec_id is embedded in both the audio
     and transcript filenames, so this is a precise join key.
  3. If a `*-transcript.md` already exists on Drive for this rec_id → skip
     (idempotent re-runs).
  4. Else, if a `.mp3` exists on Drive → upload the local markdown as
     `<mp3-stem>-transcript.md` (mirrors the live pipeline's naming).
  5. Else (no audio on Drive for this rec_id — never uploaded, or uploaded
     under an unrelated name) → skip, logged, nothing to attach it to.

Run from the repo root:
    venv/bin/python scripts/backfill_drive_transcripts.py --dry-run   # preview
    venv/bin/python scripts/backfill_drive_transcripts.py             # do it

Uses the existing GDRIVE_SA_JSON / GDRIVE_FOLDER_ID from .env — no new
dependencies. Never run against production Drive without reviewing --dry-run
output first.
"""
import argparse
import logging
import os
import sys
import time

# Run from anywhere: make the repo root importable so `gdrive`/`transcripts` resolve.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(REPO_ROOT, ".env"))

import gdrive  # noqa: E402
from transcripts import TRANSCRIPTS_DIR  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("backfill_drive_transcripts")

THROTTLE_SECONDS = 0.2


def _rec_id_of(stem: str) -> str:
    """Same derivation as transcripts.find_orphans: last "_"-separated token."""
    return stem.rsplit("_", 1)[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="Only print what would happen, no uploads.")
    args = parser.parse_args()

    if not gdrive.is_configured():
        print("Google Drive nie jest skonfigurowany (GDRIVE_SA_JSON / GDRIVE_FOLDER_ID) "
              "— przerywam.")
        sys.exit(1)

    if not os.path.isdir(TRANSCRIPTS_DIR):
        print(f"Brak katalogu transkryptów: {TRANSCRIPTS_DIR}")
        sys.exit(0)

    local_files = sorted(f for f in os.listdir(TRANSCRIPTS_DIR) if f.endswith(".md"))
    if not local_files:
        print("Brak lokalnych transkryptów (transcripts/*.md) — nic do zrobienia.")
        sys.exit(0)

    uploaded = skipped_already_done = skipped_no_audio = 0

    for fname in local_files:
        stem = fname[:-3]  # strip ".md"
        rec_id = _rec_id_of(stem)
        path = os.path.join(TRANSCRIPTS_DIR, fname)

        try:
            matches = gdrive.find_files(rec_id)
        except Exception as e:
            logger.error("Drive lookup failed for %s (rec_id=%s): %s", fname, rec_id, e)
            continue

        already = next((f for f in matches if f["name"].endswith("-transcript.md")), None)
        if already is not None:
            logger.info("Skip %s — already on Drive as %s", fname, already["name"])
            skipped_already_done += 1
            continue

        mp3 = next((f for f in matches if f["name"].endswith(".mp3")), None)
        if mp3 is None:
            logger.info(
                "Skip %s — no matching .mp3 on Drive for rec_id=%s "
                "(audio never uploaded, can't recover the exact filename)",
                fname, rec_id,
            )
            skipped_no_audio += 1
            continue

        target_name = mp3["name"][:-4] + "-transcript.md"  # strip ".mp3"
        if args.dry_run:
            print(f"[dry-run] would upload {fname} -> {target_name}")
            uploaded += 1
            continue

        try:
            gdrive.upload_file(path, target_name, "text/markdown")
            logger.info("Uploaded %s -> %s", fname, target_name)
            uploaded += 1
        except Exception as e:
            logger.error("Upload failed for %s: %s", fname, e)
            continue

        time.sleep(THROTTLE_SECONDS)

    verb = "Would upload" if args.dry_run else "Uploaded"
    print(
        f"\n{verb}: {uploaded} · already on Drive: {skipped_already_done} · "
        f"no audio on Drive: {skipped_no_audio} · total local: {len(local_files)}"
    )


if __name__ == "__main__":
    main()
