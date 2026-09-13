# tts.py
# Text-to-speech for Momentum's live voice replies, via the OpenAI API.
#
# Shaped deliberately like transcribe.py: same single environment variable
# (OPENAI_API_KEY), same is_configured() guard, same "blocking — call via
# asyncio.to_thread" contract. They share one key, so an exhausted balance takes
# out transcription, the model and speech together (see Known issues in CLAUDE.md);
# classify such failures with transcribe.is_quota_error().

import logging
import os
import tempfile

from config import VOICE_LIVE_TTS_MODEL, VOICE_LIVE_TTS_SPEED, VOICE_LIVE_TTS_VOICE

logger = logging.getLogger("momentum_bot.tts")


def is_configured() -> bool:
    """True when an OpenAI API key is available."""
    return bool(os.getenv("OPENAI_API_KEY"))


def _client():
    from openai import OpenAI
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def synthesize(text: str) -> str | None:
    """Synthesize ``text`` to a temporary mp3. Returns the path — the caller deletes it.

    Blocking (network + disk) — call via asyncio.to_thread. Returns None for
    empty input. Raises on API failure so the caller can log/classify it.
    """
    text = (text or "").strip()
    if not text:
        return None
    fd, out_path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        client = _client()
        resp = client.audio.speech.create(
            model=VOICE_LIVE_TTS_MODEL,
            voice=VOICE_LIVE_TTS_VOICE,
            input=text,
            speed=VOICE_LIVE_TTS_SPEED,
            response_format="mp3",
        )
        resp.write_to_file(out_path)
    except Exception:
        try:
            os.remove(out_path)
        except OSError:
            pass
        raise
    logger.info("Synthesized speech (%d chars -> %s)", len(text), os.path.basename(out_path))
    return out_path
