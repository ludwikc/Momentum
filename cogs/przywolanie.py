"""Momentum jako przywoływany uczestnik rozmowy.

Przez większość czasu milczy. Gdy ktoś zwróci się do niego po imieniu
("Momentum") albo @-wzmianką, bot czyta ostatnie wiadomości z kanału/wątku
i jednym wywołaniem modelu decyduje, czy faktycznie zaproszono go do rozmowy
(model zwraca dokładnie [CISZA], jeśli nie). Bez RAG — kontekst to wyłącznie
okno rozmowy. Logika czysta (trigger, budowa promptu) żyje w ``summon.py``.

OpenAI jest wołane tym samym wzorcem co ``transcribe.py``: synchroniczny klient
budowany z OPENAI_API_KEY, wywoływany przez ``asyncio.to_thread`` (sieć blokuje).
"""
import asyncio
import logging
import os

import discord
from discord.ext import commands

from config import (
    MOMENTUM_CONTEXT_MESSAGES,
    MOMENTUM_MAX_TOKENS,
    MOMENTUM_MODEL,
    MOMENTUM_TEMPERATURE,
)
from summon import build_summon_prompt, is_param_compat_error, is_summon

logger = logging.getLogger("momentum_bot.przywolanie")

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
        logger.info("Przywolanie cog initialized")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Never react to ourselves or other bots (prevents loops).
        if message.author.bot:
            return
        # Server channels and threads only — ignore DMs.
        if message.guild is None:
            return

        try:
            bot_mentioned = self.bot.user in message.mentions
            if not is_summon(message.content, bot_mentioned):
                return

            # No key configured → stay silent (same guard as transcribe.py).
            if not os.getenv("OPENAI_API_KEY"):
                logger.warning("Momentum przywołany, ale brak OPENAI_API_KEY — pomijam")
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
