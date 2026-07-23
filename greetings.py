"""Pure helpers for Momentum's Deep Work channel greetings.

Kept free of third-party imports (no discord/openai) so the logic is unit
testable on its own — same split as ``summon.py``. The cog ``cogs/queue_cog.py``
imports these and handles all Discord/OpenAI I/O.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

try:
    from zoneinfo import ZoneInfo

    _WARSAW = ZoneInfo("Europe/Warsaw")
except Exception:  # pragma: no cover - fallback if tzdata is unavailable
    _WARSAW = None


# Polish weekday names, keyed by ``date.weekday()`` (0 = Monday .. 6 = Sunday).
WEEKDAYS_PL = {
    0: "poniedziałek",
    1: "wtorek",
    2: "środa",
    3: "czwartek",
    4: "piątek",
    5: "sobota",
    6: "niedziela",
}


# Static fallback pool, used when the LLM call fails/times out (or is disabled).
# The original six greetings stay in the pool; the rest broaden the variety so a
# fallback day still doesn't feel repetitive.
DEEPWORK_HELLOS_FALLBACK = [
    "Nad czym będziesz dziś pracować?",
    "Co jest dzisiaj Twoim MIT (Most Important Task)?",
    "Jaki efekt chcesz zobaczyć za 90 minut?",
    "Co dziś dowozisz?",
    "Które zadanie z Twojej listy najbardziej Cię dziś uwiera?",
    "Czas zjeść jakąś 'żabę'? ;)",
    "Od czego zaczynasz tę sesję?",
    "Co chcesz mieć z głowy, zanim wstaniesz od biurka?",
    "Jedna rzecz, która dziś naprawdę robi różnicę — co to?",
    "Na czym się dziś skupiasz i co odpuszczasz?",
    "Jaki jest Twój pierwszy krok na najbliższe 25 minut?",
    "Co przybliży Cię dziś o krok do większego celu?",
    "Gdyby dzień miał się udać w jednym punkcie — w którym?",
    "Co dziś kończysz, a nie tylko zaczynasz?",
    "Jaką rzecz odkładasz, a warto ruszyć ją teraz?",
    "Czego potrzebujesz, żeby wejść w głęboką pracę?",
    "Co zostawiasz za drzwiami, żeby się skupić?",
    "Nad czym pracujesz — i po czym poznasz, że się udało?",
    "Jaki mały krok dziś, żeby jutro było łatwiej?",
    "Co dziś domykasz?",
]


# System prompt for the LLM greeting. Ton "niezbyt nachalny": swobodnie, konkretnie,
# jedno lekkie pytanie otwierające pracę głęboką — bez coachingowego nacisku i bez
# wykrzyknikowej przesady. Persona Momentum w skrócie.
GREETING_SYSTEM_PROMPT = (
    "Jesteś Momentum — członkiem społeczności Lifehackerów, który wita osoby "
    "wchodzące na kanał głosowy do pracy w skupieniu (Deep Work). Twoje zadanie: "
    "napisz JEDNO krótkie, ciepłe powitanie po polsku (1–2 zdania), zakończone "
    "JEDNYM lekkim pytaniem otwierającym pracę głęboką (nad czym pracuje, jaki "
    "efekt chce dziś osiągnąć itp.).\n\n"
    "TON — to najważniejsze: swobodnie i konkretnie, jak dobry kumpel, ale "
    "NIENACHALNIE. Bez coachingowego nacisku, bez patosu, bez wymuszonej "
    "kreatywności, bez wykrzyknikowej przesady. Zwracasz się do rozmówcy formami "
    "pisanymi wielką literą (Ty, Twój, Cię…). Maksymalnie jedno emoji — i tylko "
    "jeśli pasuje. Nie przedstawiaj się, nie tłumacz, czym jest Deep Work. "
    "Zwróć wyłącznie samą treść powitania, bez cudzysłowów i bez podpisu."
)


def today_key_warsaw() -> str:
    """Warsaw-local date as ``YYYY-MM-DD`` — the daily bucket for greetings.

    Fixes the previous ``date.today()`` which used the server timezone. Mirrors
    ``_today_key`` in ``cogs/przywolanie.py``.
    """
    now = datetime.now(_WARSAW) if _WARSAW else datetime.now()
    return now.date().isoformat()


def decide_greeting_action(
    mode: str, streak: int, limit: int
) -> Literal["full", "ask", "plain"]:
    """Decide what to do on a Deep Work join, from the user's stored preference.

    - ``mode == 'plain'`` → ``"plain"`` (just "Cześć @user 👋", no LLM/tracking)
    - ``mode == 'full'`` and ``streak >= limit`` → ``"ask"`` (opt-out question)
    - otherwise → ``"full"`` (LLM greeting, with static fallback)
    """
    if mode == "plain":
        return "plain"
    if streak >= limit:
        return "ask"
    return "full"


def build_greeting_prompt(
    display_name: str, weekday_pl: str, hhmm: str, recent: list[str]
) -> str:
    """Build the OpenAI ``user`` message for a personalised greeting.

    Carries light, non-DB context (name, weekday, time) plus the recently-sent
    greetings so the model can avoid repeating itself. An empty ``recent`` list
    simply omits the avoid-repetition section.
    """
    lines = [
        f"Przywitaj osobę o imieniu/nicku: {display_name}.",
        f"Dziś jest {weekday_pl}, godzina {hhmm} (czas warszawski).",
        "Dopasuj powitanie lekko do pory dnia i dnia tygodnia, ale nienachalnie.",
    ]
    if recent:
        joined = "\n".join(f"- {r}" for r in recent)
        lines.append(
            "OSTATNIE POWITANIA (unikaj podobnych sformułowań i pytań):\n" + joined
        )
    return "\n".join(lines)
