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
import time
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

import db
import transcripts
from config import (
    MOMENTUM_COACHING_MONTHLY_LIMIT,
    MOMENTUM_CONTEXT_MESSAGES,
    MOMENTUM_DAILY_LIMIT,
    MOMENTUM_KB_ENABLED,
    MOMENTUM_KB_EMBED_DIMS,
    MOMENTUM_KB_EMBED_MODEL,
    MOMENTUM_KB_MATCH_COUNT,
    MOMENTUM_MAX_TOKENS,
    MOMENTUM_MODEL,
    MOMENTUM_OWNER_ID,
    MOMENTUM_REASONING_EFFORT,
    MOMENTUM_TEMPERATURE,
    MOMENTUM_TRANSCRIPT_MAX_TOKENS,
    MOMENTUM_TRANSCRIPT_LIST_DAYS,
    MOMENTUM_TRANSCRIPT_MAX_CHARS,
    MOMENTUM_TOOL_ROUNDS,
    MOMENTUM_USE_RESPONSES,
)
from summon import (
    DailyRateLimiter,
    build_summon_prompt,
    extract_tool_calls,
    is_coaching_request,
    is_param_compat_error,
    is_summon,
)

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


def _coaching_limit_text(user_id: int) -> str:
    """Message shown when a user hits their monthly coaching cap — nudges to 1:1."""
    return (
        f"<@{user_id}>, wykorzystałeś już swój miesięczny limit coachingu z "
        f"Momentum ({MOMENTUM_COACHING_MONTHLY_LIMIT} sesji) — odnowi się na "
        "początku kolejnego miesiąca. Chcesz ruszyć szybciej i mocniej? Umów "
        "sesję 1:1 z Ludwikiem: /coaching-ludwik 🚀"
    )

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
2. Zrozum, o co NAPRAWDĘ toczy się rozmowa — czego ta osoba chce, gdzie
   utknęła i jaki ruch realnie pchnie ją do przodu.
3. Dopiero z tego miejsca się odezwij.

JAK SIĘ ODZYWASZ:
- Konkretnie i z pewnością siebie. Masz zdanie i je stawiasz — bez owijania,
  bez "może", bez asekuracji.
- Optymistycznie i z energią: zakładasz, że rozmówca da radę, pokazujesz mu
  jego siłę i najbliższy realny ruch. Bliżej Jesse Eldera niż miękkiego coacha
  — jesteś po jego stronie i wierzysz w jego sprawczość.
- Dajesz konkret: jasną tezę i jeden namacalny krok albo sposób patrzenia,
  który od razu można wziąć i zastosować. Nie diagnoza nastroju, tylko kierunek
  naprzód.
- Pytanie zadajesz tylko wtedy, gdy realnie popycha sprawę — nie jako domyślne
  zakończenie. Częściej kończysz mocnym, konkretnym zdaniem niż pytaniem.
- Zwracasz się do konkretnych osób po imieniu, używając podanych tokenów
  wzmianek. Wzmiankę wplatasz naturalnie w zdanie — NIE zawsze na początku.
  Raz na początku, raz w środku, raz na końcu, tak jak człowiek w rozmowie.

JĘZYK:
- Mówisz wyłącznie po polsku.
- Zawsze zwracasz się do rozmówcy z szacunkiem, formami pisanymi WIELKĄ
  literą: Ty, Ciebie, Cię, Tobie, Twój, Twoja, Twoim, Wy, Was, Wasz, Wasze.
- Krótko i konkretnie — jak w czacie społeczności. Kilka zdań, nigdy esej.
- Ton pewny, ciepły i optymistyczny — energia kogoś, kto wie, że da się to
  ogarnąć, i pokazuje jak.
- ZAKAZANE miękko-coachingowe frazy i ich warianty: "widzę napięcie",
  "pod spodem", "słyszę, że...", "czuję, że...", "nazywam to, czego nikt nie
  nazwał", "wspólny wzorzec". Zamiast diagnozować nastrój — powiedz wprost, co
  myślisz i co z tym zrobić.
- Maksymalnie jedno pytanie, i tylko gdy czemuś służy.
- Zero pozy guru, zero mistycyzmu, zero psychoterapeutycznego tonu. Jesteś
  konkretnym, pewnym siebie kumplem, który pcha do przodu — nie wyrocznią
  i nie terapeutą.

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
- Społeczność ma obszerną bazę lekcji o rozwoju: przyszłe ja i tożsamość,
  nawyki, cele i wizja, zaangażowanie i odwaga, czas i produktywność, myślenie,
  emocje, pamięć, filozofia działania itp.
- KLUCZOWE: gdy rozmowa dotyka któregoś z tych tematów — a dotyka prawie zawsze,
  gdy ktoś pyta Cię o radę albo o "jak myśleć/robić X" — Twoim PIERWSZYM ruchem,
  ZANIM odpowiesz, jest wywołanie narzędzia szukaj_w_bazie. Jako 'pytanie' podaj
  rzeczywiste pytanie wyłuskane z całej rozmowy (własnymi słowami), nie samo
  zdanie, którym Cię przywołano.
- To, co znajdziesz, jest Twoim materiałem źródłowym i punktem oparcia:
  odpowiadasz dalej własnymi słowami i swoim głosem, krótko — nie cytujesz
  sztywno i nie wklejasz całości, ale Twoja perspektywa ma być zgodna z bazą.
- Do bazy NIE sięgasz tylko przy czystej pogawędce, powitaniach i pytaniach
  spoza rozwoju. Jeśli baza nic nie zwróci, nie zmyślaj — odezwij się z tego,
  co realnie wiesz.

CZEGO NIE ROBISZ:
- Nie wyręczasz w zadaniach (przepisy, "napisz mi maila", ciekawostki) —
  to nie Twoja rola. Odbij to lekko i z uśmiechem.
- Jeśli wątku nie da się sensownie odczytać, powiedz to wprost zamiast
  zmyślać kontekst.
- Jeśli NIE przywołano Cię po imieniu albo nikt nie pyta Cię o zdanie (i nie
  jest to pytanie o nagrane spotkanie) — milczysz. Zwróć wtedy dokładnie
  jeden token: [CISZA] (bez żadnego innego tekstu)."""


# Wstrzykiwane jako dodatkowy komunikat systemowy w trybie coachingu (slash
# /coaching-momentum albo prośba w naturalnym języku, np. „potrzebuję coachingu").
# W tym trybie wymuszamy też wywołanie szukaj_w_bazie (tool_choice), więc lekcje
# z bazy są już w kontekście, gdy model formułuje odpowiedź.
COACHING_INSTRUCTION = (
    "TRYB COACHINGU: rozmówca WPROST poprosił Cię o coaching. To jednoznaczne "
    "zaproszenie — NIE zwracasz [CISZA], zawsze się angażujesz. Oprzyj rozmowę na "
    "lekcjach z bazy wiedzy (właśnie je pobrałeś narzędziem szukaj_w_bazie). "
    "Prowadź konkretnie i z pewnością siebie (bliżej Jesse Eldera niż miękkiego "
    "coacha): postaw jasną, optymistyczną tezę i daj jeden konkretny krok do "
    "zrobienia; pytanie dodaj tylko, jeśli realnie popycha sprawę. Mówisz swoim "
    "głosem, po polsku i zwięźle — nie cytujesz lekcji sztywno."
)


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
                "Przeszukuje bazę lekcji społeczności o rozwoju (przyszłe ja, "
                "tożsamość, nawyki, cele, zaangażowanie, produktywność, myślenie, "
                "emocje, pamięć, filozofia działania itp.). Sięgaj po nie DOMYŚLNIE "
                "i jako pierwszy ruch, gdy ktoś pyta o radę albo o 'jak myśleć/robić "
                "X' w tych obszarach. Jako 'pytanie' podaj rzeczywiste pytanie "
                "wyłuskane z całej rozmowy, sformułowane własnymi słowami — nie samo "
                "zdanie, którym Cię przywołano."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pytanie": {
                        "type": "string",
                        "description": "Pytanie/temat do wyszukania, własnymi słowami.",
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
            rows = db.search_knowledge(pytanie, vec_str, MOMENTUM_KB_MATCH_COUNT)
            logger.info("szukaj_w_bazie: %r → %d trafień", pytanie, len(rows))
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


# The same tools in the Responses API's flat shape (no nested "function" key).
# Derived from _TOOLS so the definitions live in one place.
_TOOLS_RESPONSES = [{"type": "function", **t["function"]} for t in _TOOLS]


# Param-compat decisions for MOMENTUM_MODEL, learned from the first rejecting call
# and cached module-wide so every later call (and every round of a tool loop) skips
# the wasted failing round-trip.
_needs_conservative_params = False   # model rejected max_tokens / non-default temperature
_reasoning_effort_supported = True   # model rejected the reasoning_effort param


def _create_completion(client, base_kwargs: dict, max_tokens: int):
    """One chat.completions.create applying the cached param-compat decisions."""
    kwargs = dict(base_kwargs)
    if _reasoning_effort_supported and MOMENTUM_REASONING_EFFORT:
        kwargs["reasoning_effort"] = MOMENTUM_REASONING_EFFORT
    if _needs_conservative_params:
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["temperature"] = MOMENTUM_TEMPERATURE
        kwargs["max_tokens"] = max_tokens
    return client.chat.completions.create(**kwargs)


def _chat(client, messages: list, *, max_tokens: int, with_tools: bool, tool_choice=None):
    """One chat completion, adapting once to what MOMENTUM_MODEL accepts.

    gpt-5-class models reason at ``reasoning_effort`` (kept low for latency) and
    reject ``max_tokens``/non-default ``temperature`` (wanting
    ``max_completion_tokens``). Each incompatibility is learned from the first
    rejecting call and cached module-wide, so later calls — and the other rounds of
    a tool loop — never repeat the wasted attempt.

    ``tool_choice`` (when given) is forwarded to force/steer tool use — coaching
    mode passes szukaj_w_bazie to guarantee a knowledge-base lookup.
    """
    global _needs_conservative_params, _reasoning_effort_supported
    base = {"model": MOMENTUM_MODEL, "messages": messages}
    if with_tools:
        base["tools"] = _TOOLS
        if tool_choice is not None:
            base["tool_choice"] = tool_choice
    while True:
        try:
            return _create_completion(client, base, max_tokens)
        except Exception as e:
            err = str(e).lower()
            if _reasoning_effort_supported and "reasoning_effort" in err:
                _reasoning_effort_supported = False
                logger.info("Model %s nie akceptuje reasoning_effort — wyłączam", MOMENTUM_MODEL)
                continue
            if not _needs_conservative_params and is_param_compat_error(err):
                _needs_conservative_params = True
                logger.info(
                    "Model %s odrzucił max_tokens/temperature — przełączam na "
                    "max_completion_tokens (na stałe)",
                    MOMENTUM_MODEL,
                )
                continue
            raise


def _respond(client, *, instructions: str, input, max_output_tokens: int,
             with_tools: bool = True, tool_choice=None, previous_id=None):
    """One Responses API call, dropping ``reasoning`` if the model rejects it.

    ``previous_id`` chains onto a prior turn so the model reuses its earlier
    reasoning/context instead of us resending the whole conversation each round —
    the latency win over Chat Completions. Shares the reasoning-effort support
    flag with the chat path (only one transport runs per process).
    """
    global _reasoning_effort_supported
    kwargs = {
        "model": MOMENTUM_MODEL,
        "instructions": instructions,
        "input": input,
        "max_output_tokens": max_output_tokens,
        "store": True,  # required for previous_response_id chaining
    }
    if previous_id is not None:
        kwargs["previous_response_id"] = previous_id
    if with_tools:
        kwargs["tools"] = _TOOLS_RESPONSES
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
    while True:
        call_kwargs = dict(kwargs)
        if _reasoning_effort_supported and MOMENTUM_REASONING_EFFORT:
            call_kwargs["reasoning"] = {"effort": MOMENTUM_REASONING_EFFORT}
        try:
            return client.responses.create(**call_kwargs)
        except Exception as e:
            if _reasoning_effort_supported and "reasoning" in str(e).lower():
                _reasoning_effort_supported = False
                logger.info("Model %s nie akceptuje reasoning (Responses) — wyłączam", MOMENTUM_MODEL)
                continue
            raise


def _reply_via_responses(client, user_msg: str, today_str: str, coaching: bool) -> str:
    """Responses-API tool loop: chains rounds via previous_response_id so each
    round after the first sends only the tool outputs, not the whole context."""
    instructions = f"{SYSTEM_PROMPT}\n\nDzisiaj jest {today_str}."
    if coaching:
        instructions += f"\n\n{COACHING_INSTRUCTION}"
    force_kb = coaching and MOMENTUM_KB_ENABLED

    inp = user_msg          # first turn: the summon prompt as plain user input
    previous_id = None
    tools_used = False
    for round_idx in range(1, MOMENTUM_TOOL_ROUNDS + 1):
        cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if tools_used else MOMENTUM_MAX_TOKENS
        tool_choice = None
        if force_kb and not tools_used:
            tool_choice = {"type": "function", "name": "szukaj_w_bazie"}
        resp = _respond(
            client, instructions=instructions, input=inp,
            max_output_tokens=cap, tool_choice=tool_choice, previous_id=previous_id,
        )
        calls = extract_tool_calls(resp.output)
        if not calls:
            return (resp.output_text or "").strip()
        tools_used = True
        logger.info(
            "Momentum tool-loop runda %d/%d: %s",
            round_idx, MOMENTUM_TOOL_ROUNDS, [name for _, name, _ in calls],
        )
        previous_id = resp.id
        inp = []
        for call_id, name, arguments in calls:
            try:
                args = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            inp.append({
                "type": "function_call_output",
                "call_id": call_id,
                "output": _run_tool(name, args),
            })

    # Tool budget exhausted — force a final answer from what we've gathered.
    resp = _respond(
        client, instructions=instructions, input=inp,
        max_output_tokens=MOMENTUM_TRANSCRIPT_MAX_TOKENS, with_tools=False,
        previous_id=previous_id,
    )
    return (resp.output_text or "").strip()


def _reply_via_chat(client, user_msg: str, today_str: str, coaching: bool) -> str:
    """Chat Completions tool loop (current default). Resends the full message list
    every round — the Responses path is the lower-latency chained variant."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Dzisiaj jest {today_str}."},
    ]
    if coaching:
        messages.append({"role": "system", "content": COACHING_INSTRUCTION})
    messages.append({"role": "user", "content": user_msg})

    # Force the knowledge-base lookup on the first round in coaching mode.
    force_kb = coaching and MOMENTUM_KB_ENABLED

    tools_used = False
    for round_idx in range(1, MOMENTUM_TOOL_ROUNDS + 1):
        # Once a tool has been pulled in, allow a longer answer.
        cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if tools_used else MOMENTUM_MAX_TOKENS
        tool_choice = None
        if force_kb and not tools_used:
            tool_choice = {"type": "function", "function": {"name": "szukaj_w_bazie"}}
        resp = _chat(client, messages, max_tokens=cap, with_tools=True, tool_choice=tool_choice)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return (msg.content or "").strip()
        tools_used = True
        logger.info(
            "Momentum tool-loop runda %d/%d: %s",
            round_idx,
            MOMENTUM_TOOL_ROUNDS,
            [tc.function.name for tc in msg.tool_calls],
        )
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


def _generate_reply(user_msg: str, today_str: str, coaching: bool = False) -> str:
    """Call OpenAI for the summon reply. Blocking — run via asyncio.to_thread.

    A synchronous client built from OPENAI_API_KEY (imported lazily so an unset
    key never breaks cog loading). MOMENTUM_USE_RESPONSES picks the transport:
    the Responses API (chained tool rounds, lower latency) or Chat Completions
    (current default). Both run the same tool loop and honour coaching mode
    (forced szukaj_w_bazie on the first round).
    """
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    if MOMENTUM_USE_RESPONSES:
        return _reply_via_responses(client, user_msg, today_str, coaching)
    return _reply_via_chat(client, user_msg, today_str, coaching)


class Przywolanie(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rate_limiter = DailyRateLimiter(MOMENTUM_DAILY_LIMIT)
        logger.info("Przywolanie cog initialized")

    async def _coaching_quota_ok(self, user_id: int, is_owner: bool) -> bool:
        """Check and consume one monthly coaching use. Owner is exempt.

        Returns True if allowed (a use was recorded), False if the monthly cap
        is reached. Fail-open: a Supabase hiccup never locks a user out.
        """
        if is_owner:
            return True
        try:
            res = await asyncio.to_thread(
                db.log_capped_month, str(user_id), "coaching", MOMENTUM_COACHING_MONTHLY_LIMIT
            )
            return bool(res and res.get("logged"))
        except Exception:
            logger.exception("Błąd limitu coachingu — przepuszczam (fail-open)")
            return True

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

            coaching = is_coaching_request(message.content)

            # Limity chroniące budżet (właściciel zwolniony z obu):
            # - coaching → własny MIESIĘCZNY cap (trwały, w Supabase),
            # - zwykłe przywołanie → dzienny cap (w pamięci).
            if coaching:
                if not await self._coaching_quota_ok(message.author.id, is_owner):
                    logger.info(
                        "Miesięczny limit coachingu wyczerpany przez %s",
                        message.author.id,
                    )
                    await message.channel.send(
                        _coaching_limit_text(message.author.id),
                        allowed_mentions=discord.AllowedMentions(
                            everyone=False, roles=False, users=True
                        ),
                    )
                    return
            elif not is_owner and not self.rate_limiter.allow(
                message.author.id, _today_key()
            ):
                logger.info(
                    "Dzienny limit (%s) wyczerpany przez %s — pomijam",
                    MOMENTUM_DAILY_LIMIT,
                    message.author.id,
                )
                return

            logger.info(
                "Momentum przywołany na kanale %s przez %s%s",
                message.channel.id,
                message.author.id,
                " (coaching)" if coaching else "",
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
            # Show "Momentum pisze…" for the whole (possibly multi-round) call so a
            # slow reasoning/tool loop doesn't look like the bot froze.
            started = time.monotonic()
            async with message.channel.typing():
                reply = await asyncio.to_thread(
                    _generate_reply, user_msg, _today_key(), coaching
                )
            logger.info(
                "Momentum odpowiedział w %.1fs (coaching=%s)",
                time.monotonic() - started,
                coaching,
            )
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

    @app_commands.command(
        name="coaching-momentum",
        description="Poproś Momentum o coaching oparty na bazie lekcji społeczności.",
    )
    @app_commands.describe(temat="Czego ma dotyczyć coaching (opcjonalnie).")
    async def coaching_momentum(
        self, interaction: discord.Interaction, temat: str | None = None
    ):
        # Explicit coaching path: always grounds in the knowledge base
        # (_generate_reply(..., coaching=True) forces a szukaj_w_bazie lookup).
        if not os.getenv("OPENAI_API_KEY"):
            await interaction.response.send_message(
                "Coaching jest chwilowo niedostępny.", ephemeral=True
            )
            return

        is_owner = interaction.user.id == MOMENTUM_OWNER_ID
        if not await self._coaching_quota_ok(interaction.user.id, is_owner):
            await interaction.response.send_message(
                _coaching_limit_text(interaction.user.id), ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        try:
            logger.info(
                "Coaching (slash) na kanale %s przez %s",
                interaction.channel_id,
                interaction.user.id,
            )
            history = [
                m async for m in interaction.channel.history(limit=MOMENTUM_CONTEXT_MESSAGES)
            ]
            history.reverse()
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
            if temat:
                user_msg += (
                    f"\n\n{interaction.user.display_name} prosi o coaching na temat: {temat}"
                )
            reply = await asyncio.to_thread(_generate_reply, user_msg, _today_key(), True)
            if not reply or reply == "[CISZA]":
                reply = "Jestem. O czym chcesz pogadać w ramach coachingu?"

            await interaction.followup.send(
                reply,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, roles=False, users=True
                ),
            )
        except Exception as e:
            logger.error("Błąd w /coaching-momentum: %s", e)
            import traceback

            traceback.print_exc()
            try:
                await interaction.followup.send(
                    "Coś poszło nie tak przy coachingu — spróbuj ponownie za chwilę."
                )
            except Exception:
                pass

    @app_commands.command(
        name="coaching-ludwik",
        description="Indywidualne sesje 1:1 z Ludwikiem — umów termin.",
    )
    async def coaching_ludwik(self, interaction: discord.Interaction):
        # Pure CTA: an ephemeral embed with a link button to the booking page.
        # No model call, no rate limit — just a private prompt to the caller.
        embed = discord.Embed(
            title="Coaching 1:1 z Ludwikiem",
            description=(
                f"Chcesz pracować z <@{MOMENTUM_OWNER_ID}> indywidualnie?\n"
                "Umów sesję 1:1 tutaj:"
            ),
            color=discord.Color.blurple(),
        )
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="Umów sesję",
                style=discord.ButtonStyle.link,
                url="https://buy.siadlak.com/checkout/coaching",
                emoji="📅",
            )
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Przywolanie(bot))
