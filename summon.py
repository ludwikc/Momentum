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

# Coaching request: matches the "coach" stem so Polish inflections work too
# ("coaching", "coachingu", "coacha", "coachem"). When a summon matches this,
# Momentum is forced to consult the knowledge base before replying.
_COACHING_RE = re.compile(r"\bcoach", re.IGNORECASE)

_PARTICIPANTS_HEADER = (
    "Uczestnicy rozmowy (użyj dokładnie tych tokenów, gdy zwracasz się do kogoś):"
)
_CLOSING_INSTRUCTION = (
    "Zostałeś przywołany w tej rozmowie. Odezwij się zgodnie ze swoją rolą albo, "
    "jeśli to nie była prośba o Twoje zdanie, zwróć dokładnie: [CISZA]"
)
# Used when the bot is addressed DIRECTLY (an explicit @mention, or a 1:1 DM):
# that is an unambiguous request for its attention, so the [CISZA] escape hatch
# is dropped — staying silent on a direct ping reads as the bot being broken.
# If the message is terse or leans on earlier context ("a Ty wiesz?"), the model
# answers from the transcript above or asks a short clarifying question instead
# of going quiet.
_CLOSING_INSTRUCTION_DIRECT = (
    "Zostałeś WPROST przywołany po imieniu (albo ktoś pisze do Ciebie bezpośrednio) "
    "w tej rozmowie — to jednoznaczna prośba o Twoją uwagę. Odezwij się zgodnie ze "
    "swoją rolą i NIE zwracaj [CISZA] — zawsze się angażujesz. Jeśli pytanie jest "
    "krótkie lub zależy od wcześniejszego kontekstu, oprzyj się na powyższej rozmowie; "
    "a jeśli naprawdę nie wiadomo, o co chodzi, dopytaj zamiast milczeć."
)


def is_summon(content: str, bot_mentioned: bool) -> bool:
    """True only when the bot is @-mentioned or the whole word 'momentum' appears."""
    return bot_mentioned or bool(_SUMMON_RE.search(content))


def is_coaching_request(content: str) -> bool:
    """True when the message explicitly asks for coaching (e.g. 'potrzebuję coachingu').

    Used on top of ``is_summon`` to switch Momentum into coaching mode, which
    forces a knowledge-base lookup before it replies.
    """
    return bool(_COACHING_RE.search(content or ""))


class DailyRateLimiter:
    """In-memory per-user daily call counter.

    Used to cap token-costly OpenAI calls: each user may be allowed a fixed
    number of calls per ``day_key`` (a caller-supplied day string, e.g. the
    Warsaw-local date). Counts live in memory and reset both when the day key
    changes and on process restart — deliberately avoiding a DB round-trip for
    a soft, best-effort throttle.

    Kept here (no discord/openai imports) so it is unit-testable in isolation,
    same split as the rest of this module.
    """

    def __init__(self, limit: int):
        self.limit = limit
        # user_id -> (day_key, count_so_far_today)
        self._counts: dict[int, tuple[str, int]] = {}

    def allow(self, user_id: int, day_key: str) -> bool:
        """Record one use for ``user_id`` on ``day_key``; True if under the limit.

        A non-positive ``limit`` means unlimited (always True, nothing tracked).
        The use is only counted when allowed, so a blocked user does not push
        their own counter higher on every rejected attempt.
        """
        if self.limit <= 0:
            return True
        day, count = self._counts.get(user_id, (day_key, 0))
        if day != day_key:
            count = 0
        if count >= self.limit:
            self._counts[user_id] = (day_key, count)
            return False
        self._counts[user_id] = (day_key, count + 1)
        return True


def is_param_compat_error(message: str) -> bool:
    """True when an OpenAI error looks like a model parameter-compatibility issue.

    Newer models (gpt-5 class) reject ``max_tokens`` and a non-default
    ``temperature`` (asking for ``max_completion_tokens`` / the default instead).
    When the error names one of those parameters, the caller should retry with
    the conservative parameter set rather than give up.
    """
    lowered = message.lower()
    return any(hint in lowered for hint in ("max_tokens", "max_completion_tokens", "temperature"))


def extract_tool_calls(output) -> list[tuple[str, str, str]]:
    """From a Responses ``output`` list, return ``(call_id, name, arguments)`` for
    each ``function_call`` item, in order.

    Non-tool items (assistant text, reasoning) are skipped. Kept here (no openai
    import) so the Responses tool-loop plumbing stays unit-testable.
    """
    calls: list[tuple[str, str, str]] = []
    for item in output:
        if getattr(item, "type", None) == "function_call":
            calls.append((item.call_id, item.name, item.arguments or ""))
    return calls


def build_summon_prompt(
    window: list[dict], bot_user_id: int, direct_mention: bool = False
) -> str:
    """Build the OpenAI ``user`` message: participants map + transcript + closing.

    ``window`` is a chronological list of ``{"author_id": int, "display_name":
    str, "is_bot": bool, "content": str}``. The bot's own messages are labelled
    ``Momentum``. The participants map lists only real (non-bot) speakers,
    de-duplicated in first-appearance order, as ``display name = <@id>`` so the
    model can ping them.

    ``direct_mention`` swaps the closing instruction: when True (an explicit
    @mention or a 1:1 DM) the [CISZA] escape hatch is dropped so the bot never
    ignores a message aimed straight at it; when False (summoned by the loose
    word "momentum") [CISZA] stays available for messages not actually addressed
    to it.
    """
    closing = _CLOSING_INSTRUCTION_DIRECT if direct_mention else _CLOSING_INSTRUCTION
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

    return f"{participants_block}\n\n{transcript}\n\n{closing}"
