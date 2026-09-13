"""Pure helpers for Momentum's live voice replies (``cogs/voice_live.py``).

Stdlib only — no discord/openai imports — so the wake-word rule, the
speech-cleanup and the PCM framing are unit-testable on their own. Same split as
``summon.py`` / ``parsers.py``: the cog owns all Discord and OpenAI I/O.
"""
from __future__ import annotations

import re
import wave

from config import (
    VOICE_LIVE_MAX_REPLY_CHARS,
    VOICE_LIVE_WAKE_WINDOW_WORDS,
    VOICE_LIVE_WAKE_WORDS,
)

# Audio format of everything voice_recv hands us (and everything we hand back):
# 20 ms frames of 48 kHz stereo 16-bit PCM. Mirrors mixsink's constants.
PCM_RATE = 48000
PCM_CHANNELS = 2
PCM_WIDTH = 2

# Whisper glues punctuation onto words ("Momentum,"), and Polish needs its own
# letters kept. Everything else is stripped before comparing to a wake word.
_WORD_KEEP_RE = re.compile(r"[^a-z0-9ąćęłńóśźż]")


def normalize_word(word: str) -> str:
    """Lowercase and strip punctuation: ``'„Momentum”.'`` -> ``'momentum'``."""
    return _WORD_KEEP_RE.sub("", (word or "").lower())


def has_wake_word(
    text: str,
    *,
    words: tuple[str, ...] = VOICE_LIVE_WAKE_WORDS,
    window: int = VOICE_LIVE_WAKE_WINDOW_WORDS,
) -> bool:
    """True when a wake word falls within the first ``window`` words of ``text``.

    Deliberately STRICTER than ``summon.is_summon``, which matches "momentum"
    anywhere in a message. On a text channel a mid-sentence mention is harmless;
    on voice it would make the bot speak out loud over an ongoing conversation
    every time somebody referred to it. Requiring the wake word up front is the
    "Hey Siri" convention and is what separates "Momentum, co myślisz?" from
    "…myślę, że Momentum to dobry pomysł".

    A short lead-in still works ("Hej Momentum, …", "OK Momentum, …"). The flip
    side is inherent to any positional rule: "No i Momentum powiedział" also
    passes, because position alone cannot tell it from "Hej no Momentum, …".
    Tighten ``window`` to trade that off.
    """
    if not text or window <= 0 or not words:
        return False
    wanted = {normalize_word(w) for w in words}
    wanted.discard("")
    if not wanted:
        return False
    seen = 0
    for token in text.split():
        norm = normalize_word(token)
        if not norm:
            continue  # standalone punctuation doesn't consume a slot
        if norm in wanted:
            return True
        seen += 1
        if seen >= window:
            return False
    return False


# Everything below turns a Discord-flavoured model reply into something a TTS
# engine can read out loud. Order matters: markdown links are unwrapped before
# bare URLs are collapsed, or the link text would be eaten too.
_MENTION_RE = re.compile(r"<(?:@[!&]?|#)\d+>")          # <@123> <@!123> <@&123> <#123>
_CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")           # <:nazwa:123> <a:nazwa:123>
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_URL_RE = re.compile(r"<?https?://\S+>?")
_LINE_PREFIX_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)]|>+|#{1,6})\s+", re.MULTILINE)
_MD_MARKS_RE = re.compile(r"(\*{1,3}|_{1,3}|~~|`)")
_SPACES_RE = re.compile(r"[ \t]{2,}")
_BLANKS_RE = re.compile(r"\n{3,}")
_SENTENCE_END = ".!?…"


def strip_for_speech(text: str, *, limit: int = VOICE_LIVE_MAX_REPLY_CHARS) -> str:
    """Model reply -> plain text suitable for speech synthesis.

    Removes what cannot be spoken: Discord tokens (a TTS engine reads ``<@123>``
    out literally), markdown emphasis/bullets/headings, code blocks, and URLs
    (collapsed to the word "link"). Then trims to ``limit``, preferring a
    sentence boundary and falling back to a word boundary, so the bot never ends
    mid-word. Returns "" for empty input.
    """
    if not text:
        return ""
    out = _CODE_BLOCK_RE.sub(" ", text)
    out = _CUSTOM_EMOJI_RE.sub(" ", out)
    out = _MENTION_RE.sub(" ", out)
    out = _MD_LINK_RE.sub(r"\1", out)
    out = _URL_RE.sub("link", out)
    out = _LINE_PREFIX_RE.sub("", out)
    out = _MD_MARKS_RE.sub("", out)
    out = _SPACES_RE.sub(" ", out)
    out = _BLANKS_RE.sub("\n\n", out)
    out = "\n".join(line.strip() for line in out.splitlines()).strip()
    if limit > 0 and len(out) > limit:
        out = _truncate(out, limit)
    return out


def _truncate(text: str, limit: int) -> str:
    """Cut ``text`` to ``limit``, preferring a sentence then a word boundary.

    A boundary is only accepted in the second half of the window, so an early
    full stop can't shrink a 600-char budget to 30 chars.
    """
    window = text[:limit]
    cut = max(window.rfind(c) for c in _SENTENCE_END)
    if cut >= limit // 2:
        return window[: cut + 1].strip()
    cut = window.rfind(" ")
    if cut >= limit // 2:
        return window[:cut].strip()
    return window.strip()


def pcm_to_wav(pcm: bytes, path: str) -> str:
    """Write raw 48 kHz/stereo/16-bit PCM to ``path`` as a WAV. Returns ``path``.

    The live utterance buffers come straight off the sink as raw frames; Whisper
    needs a container, and ``transcribe.transcribe`` re-encodes from a file.
    """
    with wave.open(path, "wb") as wav:
        wav.setnchannels(PCM_CHANNELS)
        wav.setsampwidth(PCM_WIDTH)
        wav.setframerate(PCM_RATE)
        wav.writeframes(pcm)
    return path
