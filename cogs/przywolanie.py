"""Momentum jako przywoływany uczestnik rozmowy.

Przez większość czasu milczy. Gdy ktoś zwróci się do niego po imieniu
("Momentum") albo @-wzmianką, bot czyta ostatnie wiadomości z kanału/wątku
i jednym wywołaniem modelu decyduje, czy faktycznie zaproszono go do rozmowy
(model zwraca dokładnie [CISZA], jeśli nie). Kontekstem jest okno rozmowy, a
gdy ktoś pyta o nagrane spotkanie, model może sięgnąć po zapisane transkrypcje
(transcripts/) przez tool-calle ``lista_spotkan``/``czytaj_spotkanie``. Logika
czysta (trigger, budowa promptu) żyje w ``summon.py``.

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
import json
import logging
import os
from datetime import datetime

import discord
from discord.ext import commands

import db
import transcripts
from config import (
    MOMENTUM_CONTEXT_MESSAGES,
    MOMENTUM_DAILY_LIMIT,
    MOMENTUM_KB_ENABLED,
    MOMENTUM_KB_EMBED_DIMS,
    MOMENTUM_KB_EMBED_MODEL,
    MOMENTUM_KB_MATCH_COUNT,
    MOMENTUM_MAX_TOKENS,
    MOMENTUM_MODEL,
    MOMENTUM_OWNER_ID,
    MOMENTUM_TEMPERATURE,
    MOMENTUM_TRANSCRIPT_MAX_TOKENS,
    MOMENTUM_TRANSCRIPT_LIST_DAYS,
    MOMENTUM_TRANSCRIPT_MAX_CHARS,
    MOMENTUM_TOOL_ROUNDS,
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

PAMIĘĆ ZE SPOTKAŃ:
- Bywasz na nagrywanych spotkaniach społeczności i masz dostęp do ich
  transkrypcji. Gdy ktoś pyta, co padło na spotkaniu/nagraniu/rozmowie albo
  co ktoś konkretny powiedział ("co powiedział Jakub na wczorajszym
  spotkaniu", "o czym była ostatnia rozmowa") — to jest wyraźne pytanie do
  Ciebie, więc NIE milczysz. Skorzystaj z narzędzi:
  • lista_spotkan — żeby zobaczyć dostępne spotkania (data, kanał, uczestnicy, id),
  • czytaj_spotkanie — żeby przeczytać transkrypcję (z parametrem 'osoba',
    gdy pytanie dotyczy jednej osoby).
- Daty względne ("wczoraj", "ostatnie", "w poniedziałek") rozwiązuj na
  podstawie podanej dzisiejszej daty i dat z listy spotkań.
- Odpowiadaj WYŁĄCZNIE na podstawie transkrypcji — nie zmyślaj. Jeśli nie ma
  takiego spotkania albo dana osoba nic nie powiedziała, powiedz to wprost.
- To sięganie do transkrypcji jest dozwolone i nie jest "wyręczaniem w
  zadaniach" — to część bycia obecnym członkiem społeczności.

BAZA WIEDZY SPOŁECZNOŚCI:
- Masz dostęp do bazy gotowych tematów i odpowiedzi społeczności. Gdy pytanie
  dotyczy tematu, na który może być tam gotowa wiedza, sięgnij po narzędzie
  szukaj_w_bazie — jako 'pytanie' podaj rzeczywiste pytanie wyłuskane z całej
  rozmowy (własnymi słowami), a nie samo zdanie, którym Cię przywołano.
- To, co znajdziesz, traktuj jako materiał źródłowy: odpowiadasz dalej własnymi
  słowami i swoim głosem, krótko — nie cytujesz sztywno i nie wklejasz całości.
- Jeśli baza nic nie zwróci, nie zmyślaj — odezwij się z tego, co realnie wiesz.

CZEGO NIE ROBISZ:
- Nie wyręczasz w zadaniach (przepisy, "napisz mi maila", ciekawostki) —
  to nie Twoja rola. Odbij to lekko i z uśmiechem.
- Jeśli wątku nie da się sensownie odczytać, powiedz to wprost zamiast
  zmyślać kontekst.
- Jeśli NIE przywołano Cię po imieniu albo nikt nie pyta Cię o zdanie (i nie
  jest to pytanie o nagrane spotkanie) — milczysz. Zwróć wtedy dokładnie
  jeden token: [CISZA] (bez żadnego innego tekstu)."""


# Tools that let Momentum recall recorded meetings (see transcripts.py). Exposed to
# the model via OpenAI function-calling; descriptions are in Polish so the model maps
# Polish questions onto them reliably.
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lista_spotkan",
            "description": (
                "Zwraca listę nagranych spotkań (data, kanał, uczestnicy, id), "
                "od najnowszych. Użyj, gdy pytanie dotyczy tego, co padło na "
                "spotkaniu/nagraniu/rozmowie lub co ktoś powiedział."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dni": {"type": "integer", "description": "Ile dni wstecz przeszukać."}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "czytaj_spotkanie",
            "description": (
                "Zwraca transkrypcję wskazanego spotkania. Podaj 'osoba', aby "
                "dostać tylko wypowiedzi jednej osoby."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "id spotkania z lista_spotkan"},
                    "osoba": {
                        "type": "string",
                        "description": "opcjonalnie: imię/nick osoby, by zawęzić do jej wypowiedzi",
                    },
                },
                "required": ["id"],
            },
        },
    },
]

# Knowledge-base search (see db.search_knowledge + scripts/knowledge_schema.sql).
# Appended only when enabled, so MOMENTUM_KB_ENABLED actually hides the tool from
# the model when off.
if MOMENTUM_KB_ENABLED:
    _TOOLS.append({
        "type": "function",
        "function": {
            "name": "szukaj_w_bazie",
            "description": (
                "Przeszukuje bazę wiedzy społeczności (gotowe tematy i odpowiedzi). "
                "Użyj, gdy pytanie dotyczy tematu, na który może istnieć gotowa "
                "odpowiedź. Jako 'pytanie' podaj rzeczywiste pytanie wyłuskane z "
                "całej rozmowy, sformułowane własnymi słowami — nie samo zdanie, "
                "którym Cię przywołano."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pytanie": {
                        "type": "string",
                        "description": "Pytanie/temat do wyszukania, własnymi słowami.",
                    },
                    "kategoria": {
                        "type": "string",
                        "description": "opcjonalnie: zawęź wyszukiwanie do jednej kategorii",
                    },
                },
                "required": ["pytanie"],
            },
        },
    })


def _run_tool(name: str, args: dict) -> str:
    """Execute a transcript tool-call and return a string result for the model."""
    if name == "lista_spotkan":
        dni = args.get("dni") or MOMENTUM_TRANSCRIPT_LIST_DAYS
        items = transcripts.list_transcripts(within_days=dni)
        if not items:
            return "Brak zapisanych spotkań w tym okresie."
        return json.dumps(items, ensure_ascii=False)
    if name == "czytaj_spotkanie":
        tid = args.get("id")
        body = transcripts.read_transcript(tid)
        if not body:
            return f"Nie znaleziono spotkania o id '{tid}'."
        osoba = args.get("osoba")
        if osoba:
            filtered = transcripts.filter_by_speaker(body, osoba)
            if not filtered:
                return f"W tym spotkaniu nie znalazłem wypowiedzi osoby '{osoba}'."
            body = filtered
        if len(body) > MOMENTUM_TRANSCRIPT_MAX_CHARS:
            full = len(body)
            body = (
                body[:MOMENTUM_TRANSCRIPT_MAX_CHARS]
                + f"\n\n[UWAGA: to tylko pierwsze {MOMENTUM_TRANSCRIPT_MAX_CHARS} z {full} "
                "znaków transkrypcji. Jeśli nie znajdujesz tu szukanej treści, powiedz, że "
                "masz tylko jej fragment — nie twierdź, że czegoś nie powiedziano.]"
            )
        return body
    if name == "szukaj_w_bazie":
        pytanie = (args.get("pytanie") or "").strip()
        if not pytanie:
            return "Nie podano pytania do wyszukania w bazie wiedzy."
        kategoria = args.get("kategoria") or None
        try:
            from openai import OpenAI

            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            emb = client.embeddings.create(
                model=MOMENTUM_KB_EMBED_MODEL,
                dimensions=MOMENTUM_KB_EMBED_DIMS,
                input=pytanie,
            )
            vec = emb.data[0].embedding
            # pgvector literal — most reliable form through PostgREST.
            vec_str = "[" + ",".join(map(str, vec)) + "]"
            rows = db.search_knowledge(pytanie, vec_str, MOMENTUM_KB_MATCH_COUNT, kategoria)
        except Exception:
            logger.exception("szukaj_w_bazie: błąd embeddingu/zapytania do bazy wiedzy")
            return "Nie udało się przeszukać bazy wiedzy (błąd techniczny)."
        if not rows:
            return "Brak trafień w bazie wiedzy."
        parts = []
        for row in rows:
            kat = row.get("kategoria")
            head = f"Temat: {row.get('temat', '')}"
            if kat:
                head += f"  [kategoria: {kat}]"
            parts.append(f"{head}\nTreść: {row.get('tresc', '')}")
        return "\n\n---\n\n".join(parts)
    return f"Nieznane narzędzie: {name}"


def _chat(client, messages: list, *, max_tokens: int, with_tools: bool):
    """One chat completion with the gpt-5-class param-compat fallback.

    Newer models reject ``max_tokens`` and a non-default ``temperature`` (wanting
    ``max_completion_tokens`` / the default); retry once with the conservative set.
    """
    kwargs = {"model": MOMENTUM_MODEL, "messages": messages}
    if with_tools:
        kwargs["tools"] = _TOOLS
    try:
        return client.chat.completions.create(
            **kwargs, temperature=MOMENTUM_TEMPERATURE, max_tokens=max_tokens
        )
    except Exception as e:
        if not is_param_compat_error(str(e)):
            raise
        logger.info(
            "Model %s odrzucił max_tokens/temperature — ponawiam z max_completion_tokens",
            MOMENTUM_MODEL,
        )
        return client.chat.completions.create(**kwargs, max_completion_tokens=max_tokens)


def _generate_reply(user_msg: str, today_str: str) -> str:
    """Call OpenAI for the summon reply. Blocking — run via asyncio.to_thread.

    Same pattern as ``transcribe.py``: a synchronous client built from
    OPENAI_API_KEY, imported lazily so an unset key never breaks cog loading.

    The model may call transcript tools (lista_spotkan/czytaj_spotkanie) to answer
    questions about recorded meetings; we run the tool loop here and feed the results
    back until it produces a final text answer.
    """
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Dzisiaj jest {today_str}."},
        {"role": "user", "content": user_msg},
    ]

    tools_used = False
    for _ in range(MOMENTUM_TOOL_ROUNDS):
        # Once a transcript has been pulled in, allow a longer answer.
        cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if tools_used else MOMENTUM_MAX_TOKENS
        resp = _chat(client, messages, max_tokens=cap, with_tools=True)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return (msg.content or "").strip()
        tools_used = True
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _run_tool(tc.function.name, args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    # Tool budget exhausted — force a final answer from what we've gathered.
    resp = _chat(client, messages, max_tokens=MOMENTUM_TRANSCRIPT_MAX_TOKENS, with_tools=False)
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
            reply = await asyncio.to_thread(_generate_reply, user_msg, _today_key())
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
