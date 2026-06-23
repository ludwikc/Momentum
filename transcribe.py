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


def transcribe(audio_path: str) -> str:
    """Transcribe an audio file to text. Blocking — call via asyncio.to_thread."""
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
                response_format="text",
            )
    finally:
        try:
            os.remove(compressed)
        except OSError:
            pass
    # response_format="text" returns the transcript as a plain string.
    text = result if isinstance(result, str) else getattr(result, "text", "")
    text = (text or "").strip()
    logger.info("Transcribed %s (%d chars)", os.path.basename(audio_path), len(text))
    return text


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
