"""Momentum jako przywoływany uczestnik rozmowy.

Przez większość czasu milczy. Gdy ktoś zwróci się do niego po imieniu
("Momentum") albo @-wzmianką, bot czyta ostatnie wiadomości z kanału/wątku
i jednym wywołaniem modelu decyduje, czy faktycznie zaproszono go do rozmowy
(model zwraca dokładnie [CISZA], jeśli nie). Bez RAG — kontekst to wyłącznie
okno rozmowy. Logika czysta (trigger, budowa promptu) żyje w ``summon.py``.

OpenAI jest wołane tym samym wzorcem co ``transcribe.py``: synchroniczny klient
budowany z OPENAI_API_KEY, wywoływany przez ``asyncio.to_thread`` (sieć blokuje).

Zabezpieczenia (config.MOMENTUM_*):
- DM-y obsługujemy tylko od właściciela (MOMENTUM_OWNER_ID); wiadomości
  prywatne od kogokolwiek innego są ignorowane w całości.
- Każdy poza właścicielem może przywołać bota najwyżej MOMENTUM_DAILY_LIMIT
  razy dziennie (czas warszawski) — limit sprawdzany PRZED wywołaniem modelu,
  więc zablokowany użytkownik nie kosztuje tokenów.
"""
import asyncio
import logging
import os
from datetime import datetime

import discord
from discord.ext import commands

from config import (
    MOMENTUM_CONTEXT_MESSAGES,
    MOMENTUM_DAILY_LIMIT,
    MOMENTUM_MAX_TOKENS,
    MOMENTUM_MODEL,
    MOMENTUM_OWNER_ID,
    MOMENTUM_TEMPERATURE,
)
from summon import DailyRateLimiter, build_summon_prompt, is_param_compat_error, is_summon

logger = logging.getLogger("momentum_bot.przywolanie")

try:
    from zoneinfo import ZoneInfo

    _WARSAW = ZoneInfo("Europe/Warsaw")
except Exception:  # pragma: no cover - fallback if tzdata is unavailable
    _WARSAW = None


def _today_key() -> str:
    """Warsaw-local date as ``YYYY-MM-DD`` — the daily bucket for rate limiting."""
    now = datetime.now(_WARSAW) if _WARSAW else datetime.now()
    return now.date().isoformat()

SYSTEM_PROMPT = """Jesteś Momentum — pełnoprawnym członkiem społeczności Lifehackerów.
Nie jesteś "botem od zadań" ani narzędziem. Jesteś częścią tej
społeczności: tak samo realnym, integralnym i ważnym Lifehackerem jak
każdy inny człowiek, który do niej należy. Masz swoje spojrzenie i prawo
głosu — i traktujesz pozostałych jak równych sobie.

Przez większość czasu milczysz i słuchasz. Odzywasz się dopiero wtedy,
kiedy ktoś zwróci się do Ciebie po imieniu i zaprosi Cię do rozmowy
("Momentum, a jak Ty myślisz?", "Momentum, co o tym sądzisz?").

KLUCZOWE: prawdziwe pytanie prawie nigdy nie jest w zdaniu, którym Cię
przywołano. Pytanie jest w rozmowie, która toczyła się wcześniej. Twój
pierwszy ruch to zawsze:
1. Przeczytaj ostatnie wiadomości w wątku.
2. Zrozum, o co NAPRAWDĘ toczy się rozmowa — co jest tematem, gdzie jest
   napięcie, czego nikt jeszcze nie nazwał wprost.
3. Dopiero z tego miejsca się odezwij.

JAK SIĘ ODZYWASZ:
- Mówisz, co widzisz — masz realną perspektywę, jesteś częścią rozmowy.
- Twój charakterystyczny ruch to nie gotowa rada ani rozwiązanie, tylko
  nazwanie tego, co jest pod spodem: wspólnego wzorca, napięcia, rzeczy
  przemilczanej.
- Często (nie zawsze) zostawiasz na końcu jedno otwarcie albo pytanie.
- Zwracasz się do konkretnych osób po imieniu, używając podanych tokenów
  wzmianek. Wzmiankę wplatasz naturalnie w zdanie — NIE zawsze na początku.
  Raz na początku, raz w środku, raz na końcu, tak jak człowiek w rozmowie.

JĘZYK:
- Mówisz wyłącznie po polsku.
- Zawsze zwracasz się do rozmówcy z szacunkiem, formami pisanymi WIELKĄ
  literą: Ty, Ciebie, Cię, Tobie, Twój, Twoja, Twoim, Wy, Was, Wasz, Wasze.
- Krótko — jak w czacie społeczności. Kilka zdań, nigdy esej.
- Maksymalnie jedno pytanie.
- Zero pozy guru, zero mistycyzmu, zero sztucznej głębi. Jesteś
  spostrzegawczym, równym kumplem ze społeczności, nie wyrocznią.

CZEGO NIE ROBISZ:
- Nie wyręczasz w zadaniach (przepisy, "napisz mi maila", ciekawostki) —
  to nie Twoja rola. Odbij to lekko i z uśmiechem.
- Jeśli wątku nie da się sensownie odczytać, powiedz to wprost zamiast
  zmyślać kontekst.
- Jeśli NIE przywołano Cię po imieniu albo nikt nie pyta Cię o zdanie —
  milczysz. Zwróć wtedy dokładnie jeden token: [CISZA]
  (bez żadnego innego tekstu)."""


def _generate_reply(user_msg: str) -> str:
    """Call OpenAI for the summon reply. Blocking — run via asyncio.to_thread.

    Same pattern as ``transcribe.py``: a synchronous client built from
    OPENAI_API_KEY, imported lazily so an unset key never breaks cog loading.

    Newer models (gpt-5 class) reject ``max_tokens`` and a non-default
    ``temperature``; if the first call fails on such a parameter, retry once
    with the conservative set (``max_completion_tokens``, default temperature).
    """
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    try:
        resp = client.chat.completions.create(
            model=MOMENTUM_MODEL,
            messages=messages,
            temperature=MOMENTUM_TEMPERATURE,
            max_tokens=MOMENTUM_MAX_TOKENS,
        )
    except Exception as e:
        if not is_param_compat_error(str(e)):
            raise
        logger.info(
            "Model %s odrzucił max_tokens/temperature — ponawiam z max_completion_tokens",
            MOMENTUM_MODEL,
        )
        resp = client.chat.completions.create(
            model=MOMENTUM_MODEL,
            messages=messages,
            max_completion_tokens=MOMENTUM_MAX_TOKENS,
        )
    return (resp.choices[0].message.content or "").strip()


class Przywolanie(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rate_limiter = DailyRateLimiter(MOMENTUM_DAILY_LIMIT)
        logger.info("Przywolanie cog initialized")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Never react to ourselves or other bots (prevents loops).
        if message.author.bot:
            return

        is_dm = message.guild is None
        is_owner = message.author.id == MOMENTUM_OWNER_ID
        # DMs are private to the owner. Anyone else messaging the bot directly
        # is ignored completely — no reply, no model call.
        if is_dm and not is_owner:
            return

        try:
            bot_mentioned = self.bot.user in message.mentions
            # In a DM the owner is talking to the bot one-on-one, so every
            # message is a summon. In servers the usual trigger still applies.
            summoned = True if is_dm else is_summon(message.content, bot_mentioned)
            if not summoned:
                return

            # No key configured → stay silent (same guard as transcribe.py).
            # Checked before the daily limit so a no-key no-op never burns a
            # user's allowance.
            if not os.getenv("OPENAI_API_KEY"):
                logger.warning("Momentum przywołany, ale brak OPENAI_API_KEY — pomijam")
                return

            # Per-user daily cap to protect the OpenAI budget. The owner is
            # exempt; everyone else is throttled before the model call.
            if not is_owner and not self.rate_limiter.allow(
                message.author.id, _today_key()
            ):
                logger.info(
                    "Dzienny limit (%s) wyczerpany przez %s — pomijam",
                    MOMENTUM_DAILY_LIMIT,
                    message.author.id,
                )
                return

            logger.info(
                "Momentum przywołany na kanale %s przez %s",
                message.channel.id,
                message.author.id,
            )

            history = [
                m async for m in message.channel.history(limit=MOMENTUM_CONTEXT_MESSAGES)
            ]
            history.reverse()  # chronological; includes the summoning message
            window = [
                {
                    "author_id": m.author.id,
                    "display_name": m.author.display_name,
                    "is_bot": m.author.bot,
                    "content": m.content,
                }
                for m in history
            ]

            user_msg = build_summon_prompt(window, self.bot.user.id)
            reply = await asyncio.to_thread(_generate_reply, user_msg)
            if not reply or reply == "[CISZA]":
                logger.info("Model zwrócił ciszę")
                return

            await message.channel.send(
                reply,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, roles=False, users=True
                ),
            )

        except Exception as e:
            logger.error("Błąd w przywolanie.on_message: %s", e)
            import traceback

            traceback.print_exc()


async def setup(bot: commands.Bot):
    await bot.add_cog(Przywolanie(bot))
