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

# Sentinel the model prepends to a reply when it judges the question has
# coaching potential (see COACHING_OFFER_INSTRUCTION in cogs/przywolanie.py).
# Same strict contract as [CISZA]: only recognised at the very start of the
# reply, so a stray mention mid-text never triggers the offer.
COACHING_OFFER_SENTINEL = "[COACHING?]"
_COACHING_OFFER_RE = re.compile(
    r"\A[ \t]*" + re.escape(COACHING_OFFER_SENTINEL) + r"[ \t]*\n?(.*)", re.DOTALL
)

_PARTICIPANTS_HEADER = (
    "Uczestnicy rozmowy. Gdy zwracasz się do kogoś, wklej DOKŁADNIE jego token w "
    "formacie <@liczba> z tej listy (np. <@123>). NIGDY nie wpisuj imienia w "
    "nawiasach ostrokątnych typu <Imię> — to nie zadziała jako oznaczenie:"
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


def split_coaching_offer(text: str) -> tuple[bool, str]:
    """Split off a leading ``[COACHING?]`` sentinel from a model reply.

    Returns ``(True, rest)`` when the sentinel opens the reply (leading
    whitespace tolerated, same-line or own-line body both accepted) — ``rest``
    is the reply with the sentinel and its trailing newline/space stripped off
    (empty string for a bare sentinel). Returns ``(False, text)`` unchanged
    otherwise, including when the sentinel appears anywhere but the very start
    — same strict, start-of-string-only contract as ``[CISZA]``.
    """
    if not text:
        return False, text
    m = _COACHING_OFFER_RE.match(text)
    if not m:
        return False, text
    return True, m.group(1)


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


# Discord's hard cap on a single message's content. Kept conservative (the API
# rejects anything longer with 50035 Invalid Form Body) — one long model reply
# must become several messages, never one failed send.
DISCORD_MESSAGE_LIMIT = 2000


def split_for_discord(text: str, limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    """Split a model reply into Discord-sendable chunks of at most ``limit`` chars.

    Long replies are legitimate (e.g. "napisz gotową instrukcję do wklejenia"),
    but Discord rejects the whole message when content exceeds its cap — the
    user then gets NOTHING. Splitting preference: paragraph break, then line
    break (each only in the second half of the window, so an early boundary
    doesn't produce a needlessly tiny message), then any space, then a hard
    mid-word cut as the last resort. Chunks are stripped of edge whitespace;
    empty input yields an empty list.
    """
    text = (text or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        chunk = text[:cut].rstrip()
        if chunk:
            chunks.append(chunk)
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


def repair_mentions(text: str, window: list[dict], bot_user_id: int) -> str:
    """Fix the model's occasional pseudo-mention of a participant.

    The model is told to ping with ``<@id>`` tokens but sometimes wraps the
    display name in angle brackets instead — e.g. ``<Ludwik C. Siadlak 💎>`` or
    ``<@Ludwik C. Siadlak 💎>`` — which Discord renders as inert plain text, so
    the user never gets tagged. Using the same participant map as
    ``build_summon_prompt``, rewrite those exact bracketed name forms back to the
    real ``<@id>`` token. Only the bracketed forms are touched (never a bare name
    in prose), so this can't mangle legitimate text.
    """
    if not text:
        return text
    names: dict[str, int] = {}
    for msg in window:
        if msg["is_bot"] or msg["author_id"] == bot_user_id:
            continue
        names.setdefault(msg["display_name"], msg["author_id"])
    for name, uid in names.items():
        token = f"<@{uid}>"
        text = text.replace(f"<@{name}>", token).replace(f"<{name}>", token)
    return text
