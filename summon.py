"""Pure helpers for Momentum's conversational summoning feature.

Kept free of third-party imports (no discord/openai) so the logic is unit
testable on its own — same split as ``recording/transcribe.py``. The cog
``cogs/przywolanie.py`` imports these and handles all Discord/OpenAI I/O.
"""
from __future__ import annotations

import re

# Trigger is intentionally strict: only the whole word "momentum" (any case) or
# a direct @mention of the bot. Inflected/vocative Polish forms ("momencie",
# "momentu", ...) are NOT matched — they collide with everyday speech.
_SUMMON_RE = re.compile(r"\bmomentum\b", re.IGNORECASE)

_PARTICIPANTS_HEADER = (
    "Uczestnicy rozmowy (użyj dokładnie tych tokenów, gdy zwracasz się do kogoś):"
)
_CLOSING_INSTRUCTION = (
    "Zostałeś przywołany w tej rozmowie. Odezwij się zgodnie ze swoją rolą albo, "
    "jeśli to nie była prośba o Twoje zdanie, zwróć dokładnie: [CISZA]"
)


def is_summon(content: str, bot_mentioned: bool) -> bool:
    """True only when the bot is @-mentioned or the whole word 'momentum' appears."""
    return bot_mentioned or bool(_SUMMON_RE.search(content))


def build_summon_prompt(window: list[dict], bot_user_id: int) -> str:
    """Build the OpenAI ``user`` message: participants map + transcript + closing.

    ``window`` is a chronological list of ``{"author_id": int, "display_name":
    str, "is_bot": bool, "content": str}``. The bot's own messages are labelled
    ``Momentum``. The participants map lists only real (non-bot) speakers,
    de-duplicated in first-appearance order, as ``display name = <@id>`` so the
    model can ping them.
    """
    seen: set[int] = set()
    participant_lines: list[str] = []
    for msg in window:
        if msg["is_bot"] or msg["author_id"] in seen:
            continue
        seen.add(msg["author_id"])
        participant_lines.append(f"{msg['display_name']} = <@{msg['author_id']}>")
    participants_block = "\n".join([_PARTICIPANTS_HEADER, *participant_lines])

    transcript = "\n".join(
        f"{'Momentum' if msg['author_id'] == bot_user_id else msg['display_name']}: {msg['content']}"
        for msg in window
    )

    return f"{participants_block}\n\n{transcript}\n\n{_CLOSING_INSTRUCTION}"
