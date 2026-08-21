# transcribe.py
# Transcription + summary for voice recordings, via the OpenAI API.
#
# Configure with a single environment variable (see .env):
#   OPENAI_API_KEY - if unset, is_configured() returns False and the caller
#                    should skip transcription entirely.
#
# Both transcribe() and summarize() are blocking (network/disk + ffmpeg) and
# must be called via asyncio.to_thread from async code.

import logging
import os
import re
import subprocess
import tempfile

from config import OPENAI_TRANSCRIBE_MODEL, OPENAI_SUMMARY_MODEL

logger = logging.getLogger("momentum_bot.transcribe")

# The OpenAI audio endpoints reject files larger than 25 MB. We down-mix the
# recording to 16 kHz mono Opus first (whisper resamples to 16 kHz anyway), which
# at ~16 kbps keeps even a 2 h session well under the limit (~14 MB).
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_TRANSCRIBE_LANGUAGE = "pl"  # sessions are in Polish; the hint improves accuracy


def is_configured() -> bool:
    """True when an OpenAI API key is available."""
    return bool(os.getenv("OPENAI_API_KEY"))


def _client():
    from openai import OpenAI
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _compress_for_upload(audio_path: str) -> str:
    """Down-mix to 16 kHz mono Opus (.ogg) so the upload stays under the size cap.

    Returns the path to a temp .ogg file the caller must delete.
    """
    fd, out_path = tempfile.mkstemp(suffix=".ogg")
    os.close(fd)
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", "-i", audio_path,
         "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "16k", out_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        try:
            os.remove(out_path)
        except OSError:
            pass
        raise RuntimeError(
            f"ffmpeg compression failed ({proc.returncode}): "
            f"{proc.stderr.decode('utf-8', 'replace')[-300:]}"
        )
    return out_path


def transcribe_words(audio_path: str) -> tuple[str, list[dict]]:
    """Transcribe to text plus per-word timestamps.

    Returns ``(text, words)`` where each word is ``{"word", "start", "end"}`` (seconds
    from the start of the recording). Blocking — call via asyncio.to_thread. Word
    timestamps need ``response_format="verbose_json"``, which only ``whisper-1``
    supports; the timeline matches the diarization sidecar (both start at t=0).
    """
    compressed = _compress_for_upload(audio_path)
    try:
        size = os.path.getsize(compressed)
        if size > _MAX_UPLOAD_BYTES:
            raise RuntimeError(
                f"recording too long to transcribe ({size / 1e6:.0f} MB compressed, "
                f"limit {_MAX_UPLOAD_BYTES / 1e6:.0f} MB)"
            )
        client = _client()
        with open(compressed, "rb") as f:
            result = client.audio.transcriptions.create(
                model=OPENAI_TRANSCRIBE_MODEL,
                file=f,
                language=_TRANSCRIBE_LANGUAGE,
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )
    finally:
        try:
            os.remove(compressed)
        except OSError:
            pass
    text = (getattr(result, "text", "") or "").strip()
    words: list[dict] = []
    for w in (getattr(result, "words", None) or []):
        word = w.get("word") if isinstance(w, dict) else getattr(w, "word", None)
        start = w.get("start") if isinstance(w, dict) else getattr(w, "start", None)
        end = w.get("end") if isinstance(w, dict) else getattr(w, "end", None)
        if word and start is not None and end is not None:
            words.append({"word": word, "start": float(start), "end": float(end)})
    logger.info("Transcribed %s (%d chars, %d words)",
                os.path.basename(audio_path), len(text), len(words))
    return text, words


def transcribe(audio_path: str) -> str:
    """Transcribe an audio file to plain text. Blocking — call via asyncio.to_thread."""
    return transcribe_words(audio_path)[0]


def _speaker_at(word: dict, segments: list[dict], last: str | None) -> str | None:
    """Pick the speaker whose segment overlaps `word` the most.

    Falls back to the previous word's speaker (continuity through gaps), then to the
    nearest segment by midpoint, so every word gets attributed.
    """
    ws, we = word["start"], word["end"]
    best_name, best_overlap = None, 0.0
    for seg in segments:
        overlap = min(we, seg["end"]) - max(ws, seg["start"])
        if overlap > best_overlap:
            best_overlap, best_name = overlap, seg["name"]
    if best_overlap > 0:
        return best_name
    if last is not None:
        return last
    mid = (ws + we) / 2
    nearest = min(
        segments,
        key=lambda s: 0 if s["start"] <= mid <= s["end"] else min(abs(mid - s["start"]), abs(mid - s["end"])),
        default=None,
    )
    return nearest["name"] if nearest else None


def diarize(words: list[dict], speaker_segments: list[dict]) -> str:
    """Build a speaker-labeled transcript from word timestamps + a speaking timeline.

    `words` come from transcribe_words(); `speaker_segments` from the sink's
    `*.diarization.json`. Returns Markdown with one ``**Name:** text`` block per turn.
    Falls back to the plain joined transcript when either input is missing.
    """
    if not words:
        return ""
    plain = _join_words(words)
    if not speaker_segments:
        return plain

    segments = sorted(speaker_segments, key=lambda s: s["start"])
    turns: list[tuple[str, list[dict]]] = []
    last_name: str | None = None
    for w in words:
        name = _speaker_at(w, segments, last_name) or "?"
        if turns and turns[-1][0] == name:
            turns[-1][1].append(w)
        else:
            turns.append((name, [w]))
        last_name = name

    blocks = [f"**{name}:** {_join_words(ws)}" for name, ws in turns if _join_words(ws)]
    return "\n\n".join(blocks) if blocks else plain


def _join_words(words: list[dict]) -> str:
    """Join Whisper word tokens into readable text (no space before punctuation)."""
    text = " ".join(w["word"].strip() for w in words if w["word"].strip())
    return re.sub(r"\s+([,.!?;:…])", r"\1", text).strip()


_SUMMARY_SYSTEM_PROMPT = (
    "Jesteś asystentem, który tworzy zwięzłe notatki z nagrań sesji coachingowych "
    "i rozmów grupowych społeczności Lifehackerzy (prowadzonych po polsku). "
    "Transkrypcja pochodzi z automatycznego rozpoznawania mowy, więc może zawierać "
    "drobne błędy — interpretuj sens, nie cytuj dosłownie pomyłek. "
    "Odpowiadaj zawsze po polsku, w formacie Markdown, używając sekcji:\n"
    "**📌 Główne tematy** — punktowana lista omówionych zagadnień.\n"
    "**💡 Kluczowe wnioski** — najważniejsze myśli i spostrzeżenia.\n"
    "Pisz zwięźle i konkretnie. Pomiń small-talk i powitania."
)


def summarize(transcript: str, channel_name: str | None = None) -> str:
    """Summarize a transcript into Polish Markdown notes. Blocking."""
    if not transcript.strip():
        return ""
    context = f"Nagranie z kanału #{channel_name}.\n\n" if channel_name else ""
    client = _client()
    resp = client.chat.completions.create(
        model=OPENAI_SUMMARY_MODEL,
        messages=[
            {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": f"{context}Transkrypcja:\n\n{transcript}"},
        ],
        temperature=0.3,
    )
    summary = (resp.choices[0].message.content or "").strip()
    logger.info("Summarized transcript (%d chars in, %d chars out)",
                len(transcript), len(summary))
    return summary
