#!/usr/bin/env python3
"""Rebuild transcripts for recordings whose audio is on Drive but has no transcript.

Why this exists: when the OpenAI balance hit zero (4–12.09.2026) the recording
pipeline kept working except for transcription — audio was uploaded to Drive and
the local MP3 deleted after md5 verification, so Drive is the only copy left.
This script closes that gap: download the MP3, transcribe it, diarize it with the
local sidecar if one survived, save it locally and upload it next to the audio
under the same `<audio-stem>-transcript.md` name the pipeline uses.

Distinct from scripts/backfill_drive_transcripts.py, which only *uploads*
transcripts that already exist on disk — it never calls Whisper.

Safety properties:
  * --dry-run by default in the sense that nothing runs without an explicit mode;
    pass --apply to actually spend OpenAI credits.
  * Idempotent: a recording that already has `<stem>-transcript.md` on Drive is
    skipped, so a re-run after a partial failure costs nothing for what succeeded.
  * Diarization sidecars are READ but never deleted (unlike the live pipeline's
    _build_transcript), so a failed run can be retried with speakers intact.

Usage:
    venv/bin/python scripts/backfill_missing_transcripts.py            # list only
    venv/bin/python scripts/backfill_missing_transcripts.py --apply
    venv/bin/python scripts/backfill_missing_transcripts.py --apply --only 2026-09
"""
import argparse
import json
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import gdrive  # noqa: E402
import transcribe  # noqa: E402
import transcripts  # noqa: E402
from parsers import parse_recording_filename  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("backfill")

RECORDINGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recordings")


def find_gaps(prefix: str = "Lifehackerzy_"):
    """[(audio_file_resource, started, slug, rec_id)] for audio with no transcript on Drive."""
    files = gdrive.find_files(prefix, page_size=200)
    audio = {f["name"]: f for f in files if f["name"].lower().endswith(".mp3")}
    have = {f["name"] for f in files if f["name"].endswith("-transcript.md")}
    gaps = []
    for name, res in sorted(audio.items()):
        if f"{name[:-4]}-transcript.md" in have:
            continue
        parsed = parse_recording_filename(name)
        if not parsed:
            logger.warning("Nierozpoznana nazwa, pomijam: %s", name)
            continue
        started, slug, rec_id = parsed
        gaps.append((res, started, slug, rec_id))
    return gaps


def diarize_with_sidecar(text: str, words: list, rec_id: str, started, slug: str) -> tuple[str, bool]:
    """Label the transcript with speakers from the surviving local sidecar.

    The sidecar is named after the *WAV* the recorder wrote. Returns
    (transcript, used_diarization); falls back to the plain text when no sidecar
    survived. Never deletes the sidecar — a retry must keep speaker attribution.
    """
    wav_name = f"Lifehackerzy_{started.strftime('%Y-%m-%d-%H-%M-%S')}_{slug}_{rec_id}.wav"
    diar_path = os.path.join(RECORDINGS_DIR, wav_name + ".diarization.json")
    if not (text and words and os.path.exists(diar_path)):
        return text, False
    try:
        with open(diar_path, "r", encoding="utf-8") as f:
            segments = json.load(f).get("segments") or []
        labeled = transcribe.diarize(words, segments)
        return (labeled or text), bool(labeled)
    except Exception as e:
        logger.error("Diaryzacja %s nie powiodła się, zostaje goły tekst: %s", rec_id, e)
        return text, False


def process(res, started, slug, rec_id) -> bool:
    name = res["name"]
    logger.info("→ %s", name)
    tmp_dir = tempfile.mkdtemp(prefix="backfill-")
    mp3_path = os.path.join(tmp_dir, name)
    try:
        gdrive.download_file(res["id"], mp3_path)
        size_mb = os.path.getsize(mp3_path) / 1024 / 1024
        logger.info("   pobrano %.1f MB, transkrybuję…", size_mb)

        text, words = transcribe.transcribe_words(mp3_path)
        if not text or not text.strip():
            logger.warning("   Whisper zwrócił pusty tekst — pomijam %s", rec_id)
            return False

        transcript, diarized = diarize_with_sidecar(text, words, rec_id, started, slug)
        logger.info("   %d znaków, diaryzacja: %s", len(transcript), "TAK" if diarized else "brak sidecara")

        path = transcripts.save_transcript(
            transcript, started=started, channel_name=slug, rec_id=rec_id
        )
        if not path:
            logger.error("   Zapis lokalny nie powiódł się — %s", rec_id)
            return False

        doc = transcripts.render_document(
            transcript, started=started, channel_name=slug, rec_id=rec_id
        )
        md_name = f"{name[:-4]}-transcript.md"
        md_tmp = os.path.join(tmp_dir, md_name)
        with open(md_tmp, "w", encoding="utf-8") as f:
            f.write(doc)
        info = gdrive.upload_file(md_tmp, md_name, mime_type="text/markdown")
        logger.info("   ✅ %s → Drive (%s)", md_name, info.get("id"))
        return True
    except Exception as e:
        logger.error("   ❌ %s: %s", rec_id, e)
        return False
    finally:
        for p in (mp3_path, os.path.join(tmp_dir, f"{name[:-4]}-transcript.md")):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="faktycznie transkrybuj (kosztuje kredyty OpenAI)")
    ap.add_argument("--only", default="", help="przetwarzaj tylko nagrania, których nazwa zawiera ten fragment")
    args = ap.parse_args()

    if not gdrive.is_configured():
        sys.exit("GDRIVE_SA_JSON / GDRIVE_FOLDER_ID nie są ustawione.")
    if not transcribe.is_configured():
        sys.exit("OPENAI_API_KEY nie jest ustawiony.")

    gaps = find_gaps()
    if args.only:
        gaps = [g for g in gaps if args.only in g[0]["name"]]

    if not gaps:
        print("Brak nagrań bez transkryptu. Nic do zrobienia.")
        return

    print(f"\nNagrania bez transkryptu na Drive: {len(gaps)}\n")
    for res, started, slug, rec_id in gaps:
        wav = f"Lifehackerzy_{started.strftime('%Y-%m-%d-%H-%M-%S')}_{slug}_{rec_id}.wav"
        has_diar = os.path.exists(os.path.join(RECORDINGS_DIR, wav + ".diarization.json"))
        print(f"  {started:%Y-%m-%d %H:%M}  {slug:<24} {rec_id}  "
              f"diaryzacja: {'TAK' if has_diar else 'BRAK (będą bez mówców)'}")

    if not args.apply:
        print("\n(tryb podglądu — uruchom z --apply, żeby wykonać)")
        return

    print()
    ok = sum(process(*g) for g in gaps)
    print(f"\nGotowe: {ok}/{len(gaps)} transkryptów odtworzonych.")


if __name__ == "__main__":
    main()
