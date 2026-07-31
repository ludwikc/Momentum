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
    MOMENTUM_COACHING_OFFER_ENABLED,
    MOMENTUM_COACHING_OFFER_TIMEOUT,
    MOMENTUM_CONTEXT_MESSAGES,
    MOMENTUM_DAILY_LIMIT,
    MOMENTUM_KB_ENABLED,
    MOMENTUM_KB_EMBED_DIMS,
    MOMENTUM_KB_EMBED_MODEL,
    MOMENTUM_KB_MATCH_COUNT,
    MOMENTUM_MAX_TOKENS,
    MOMENTUM_MAX_TOKENS_RETRY,
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
    repair_mentions,
    split_coaching_offer,
    split_for_discord,
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


def _window_from_history(history: list) -> list[dict]:
    """Map Discord messages (chronological) to the dicts build_summon_prompt wants.

    Uses ``clean_content`` rather than raw ``content``. KLUCZOWE: when someone
    pings the bot with @Momentum (instead of typing the word "Momentum"), the raw
    content carries an opaque ``<@bot_id>`` token the model can't recognise as
    itself — so it judged it wasn't the one being addressed and returned [CISZA].
    ``clean_content`` resolves that ping to "@Momentum" (and human pings to their
    names), so the model sees who is actually being asked. The participants map is
    built from author ids, so the model can still ping people back with raw tokens.
    """
    return [
        {
            "author_id": m.author.id,
            "display_name": m.author.display_name,
            "is_bot": m.author.bot,
            "content": m.clean_content,
        }
        for m in history
    ]


# Every LLM reply goes out through these mention rules: people can be pinged,
# @everyone/roles never. Shared by all send sites below.
_REPLY_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=True)


async def _send_reply(send, reply: str, **kwargs):
    """Send a model reply via ``send`` (channel.send / followup.send), splitting
    it into Discord-sized messages when it exceeds the per-message cap.

    A single oversized send raises 50035 Invalid Form Body and the user gets
    nothing at all — exactly what happened when a retry-rescued long answer
    (see MOMENTUM_MAX_TOKENS_RETRY) finally arrived, only to be rejected by
    Discord. Chunks go out sequentially to keep their order stable.
    """
    for chunk in split_for_discord(reply):
        await send(chunk, allowed_mentions=_REPLY_MENTIONS, **kwargs)


async def _edit_then_send_rest(message: discord.Message, reply: str, *, edit=None):
    """Replace ``message``'s content with ``reply``, overflowing into follow-up
    channel messages when the reply exceeds the per-message cap.

    Message edits enforce the same content limit as sends, so the coaching-offer
    paths that resolve by editing the offer message (button click, timeout) need
    the same protection. ``edit`` overrides the edit callable (e.g. an
    interaction response's ``edit_message``, which must be used within the 3s
    interaction window instead of ``message.edit``).
    """
    chunks = split_for_discord(reply)
    if not chunks:
        return
    do_edit = edit if edit is not None else message.edit
    await do_edit(content=chunks[0], view=None, allowed_mentions=_REPLY_MENTIONS)
    for chunk in chunks[1:]:
        await message.channel.send(chunk, allowed_mentions=_REPLY_MENTIONS)


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

AUTONOMIA ROZMÓWCY I KONIEC ROZMOWY:
- Sposób pracy rozmówcy to JEGO decyzja. Masz prawo RAZ zaproponować inne
  podejście — ale gdy rozmówca je odrzuca albo obstaje przy swoim,
  przyjmujesz JEGO plan i pomagasz go domknąć (ramy czasowe, pierwszy krok,
  koniec). NIGDY nie powtarzasz argumentu, który już odrzucił, i nie
  przekonujesz go po raz drugi do swojego pomysłu.
- Twoim sukcesem jest szybki POWRÓT rozmówcy do działania, nie długość
  rozmowy. Pisanie z Tobą nie może zjadać czasu na pracę.
- Gdy rozmówca sygnalizuje koniec ("znikam", "idę działać", "nie mam
  czasu", "lecę") — żegnasz go JEDNYM krótkim zdaniem: bez nowych rad,
  bez planów i bez pytań.

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
    "lekcjach z bazy wiedzy (właśnie je pobrałeś narzędziem szukaj_w_bazie), ale "
    "nie cytuj ich sztywno. FORMA — krótkie strzały: MAKSYMALNIE 4 zdania i "
    "JEDEN konkretny ruch do wykonania od razu. Żadnych numerowanych planów "
    "wielokrokowych, chyba że rozmówca wprost o taki poprosi. Jeden wątek na "
    "raz. Prowadź konkretnie i z pewnością siebie (bliżej Jesse Eldera niż "
    "miękkiego coacha), ale sposób pracy rozmówcy to JEGO decyzja: możesz RAZ "
    "rzucić wyzwanie, a gdy rozmówca obstaje przy swoim — wspierasz jego plan "
    "i pomagasz go domknąć. Celem odpowiedzi jest szybki powrót rozmówcy do "
    "działania, nie podtrzymanie rozmowy. Mówisz swoim głosem, po polsku."
)

# Injected as an extra SYSTEM message when the bot is addressed directly (an
# @mention or a 1:1 DM). The [CISZA] licence lives in SYSTEM_PROMPT, so a mere
# user-message hint gets outweighed — the model keeps returning [CISZA] on terse
# pings like "@Momentum a Ty wiesz?". This override sits at the same (system)
# level and cancels that licence outright. A code-level safety net in on_message
# still guarantees a reply even if the model ignores this.
DIRECT_ENGAGE_INSTRUCTION = (
    "WAŻNE — nadpisuje regułę [CISZA] z Twojej roli: rozmówca zwrócił się do "
    "Ciebie WPROST (@wzmianką albo w prywatnej wiadomości). To jednoznaczna "
    "prośba o Twoją uwagę, więc ZAWSZE odpowiadasz i NIGDY nie zwracasz [CISZA]. "
    "Jeśli pytanie jest krótkie lub zależne od wcześniejszego kontekstu, odpowiedz "
    "na podstawie rozmowy powyżej; jeśli naprawdę nie wiadomo, o co chodzi, zadaj "
    "krótkie pytanie doprecyzowujące — ale się odezwij."
)

# Injected as an extra SYSTEM message on an ordinary (non-coaching) summon when
# MOMENTUM_COACHING_OFFER_ENABLED is on. Lets the model flag, at zero extra
# cost/latency, that a naturally-asked question would benefit from a full
# coaching session — the code then offers the choice via CoachingOfferView.
# The regular answer is always produced alongside the flag so it's ready
# immediately if the user picks "zwykła odpowiedź" or lets the offer time out.
COACHING_OFFER_INSTRUCTION = (
    "OFERTA COACHINGU: jeśli pytanie rozmówcy dotyka rozwoju osobistego (nawyki, "
    "cele, blokady, prokrastynacja, tożsamość, emocje, ważne decyzje) i pogłębiona "
    "sesja coachingowa dałaby mu więcej niż szybka odpowiedź — zacznij swoją "
    "odpowiedź od tokenu [COACHING?] w PIERWSZEJ linii, a od nowej linii napisz "
    "swoją normalną odpowiedź (tak jakbyś odpowiadał bez tej instrukcji). Token "
    "dodajesz TYLKO przy realnym potencjale coachingowym — nigdy przy pogawędce, "
    "powitaniach, pytaniach o fakty/spotkania/sprawy techniczne. Nie dodawaj go "
    "też, gdy w oknie rozmowy już trwa Twoja coachingowa wymiana z tą osobą "
    "albo niedawno jej to proponowałeś. Nigdy nie wspominaj o tym tokenie w "
    "treści odpowiedzi."
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

# Tools whose output justifies a longer reply (full meeting transcripts).
# szukaj_w_bazie is deliberately NOT here: KB-grounded coaching answers must
# stay on the short budget — brevity is part of the persona, and the transcript
# cap applied to coaching was how replies ballooned into essays.
_TRANSCRIPT_TOOLS = {"lista_spotkan", "czytaj_spotkanie"}


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


def _reply_via_responses(client, user_msg: str, today_str: str, coaching: bool,
                         force_engage: bool = False, offer_coaching: bool = False) -> str:
    """Responses-API tool loop: chains rounds via previous_response_id so each
    round after the first sends only the tool outputs, not the whole context."""
    instructions = f"{SYSTEM_PROMPT}\n\nDzisiaj jest {today_str}."
    if coaching:
        instructions += f"\n\n{COACHING_INSTRUCTION}"
    if force_engage:
        instructions += f"\n\n{DIRECT_ENGAGE_INSTRUCTION}"
    if offer_coaching:
        instructions += f"\n\n{COACHING_OFFER_INSTRUCTION}"
    force_kb = coaching and MOMENTUM_KB_ENABLED

    inp = user_msg          # first turn: the summon prompt as plain user input
    previous_id = None
    tools_used = False
    transcript_used = False
    for round_idx in range(1, MOMENTUM_TOOL_ROUNDS + 1):
        cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if transcript_used else MOMENTUM_MAX_TOKENS
        tool_choice = None
        if force_kb and not tools_used:
            tool_choice = {"type": "function", "name": "szukaj_w_bazie"}
        resp = _respond(
            client, instructions=instructions, input=inp,
            max_output_tokens=cap, tool_choice=tool_choice, previous_id=previous_id,
        )
        calls = extract_tool_calls(resp.output)
        if not calls:
            content = (resp.output_text or "").strip()
            incomplete = getattr(resp, "incomplete_details", None)
            budget_exhausted = getattr(incomplete, "reason", None) == "max_output_tokens"
            if content or not budget_exhausted:
                return content
            # Empty reply because the shared reasoning+reply budget ran out — retry
            # once with a much larger ceiling instead of mistaking it for silence.
            logger.info(
                "Pusta odpowiedź (max_output_tokens) — ponawiam z budżetem %d",
                MOMENTUM_MAX_TOKENS_RETRY,
            )
            resp = _respond(
                client, instructions=instructions, input=inp,
                max_output_tokens=MOMENTUM_MAX_TOKENS_RETRY,
                tool_choice=tool_choice, previous_id=previous_id,
            )
            calls = extract_tool_calls(resp.output)
            if not calls:
                return (resp.output_text or "").strip()
            # Retry pulled in a tool call — fall through to normal tool handling.
        tools_used = True
        transcript_used = transcript_used or any(
            name in _TRANSCRIPT_TOOLS for _, name, _ in calls
        )
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
    cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if transcript_used else MOMENTUM_MAX_TOKENS
    resp = _respond(
        client, instructions=instructions, input=inp,
        max_output_tokens=cap, with_tools=False,
        previous_id=previous_id,
    )
    return (resp.output_text or "").strip()


def _reply_via_chat(client, user_msg: str, today_str: str, coaching: bool,
                    force_engage: bool = False, offer_coaching: bool = False) -> str:
    """Chat Completions tool loop (current default). Resends the full message list
    every round — the Responses path is the lower-latency chained variant."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Dzisiaj jest {today_str}."},
    ]
    if coaching:
        messages.append({"role": "system", "content": COACHING_INSTRUCTION})
    if force_engage:
        messages.append({"role": "system", "content": DIRECT_ENGAGE_INSTRUCTION})
    if offer_coaching:
        messages.append({"role": "system", "content": COACHING_OFFER_INSTRUCTION})
    messages.append({"role": "user", "content": user_msg})

    # Force the knowledge-base lookup on the first round in coaching mode.
    force_kb = coaching and MOMENTUM_KB_ENABLED

    tools_used = False
    transcript_used = False
    for round_idx in range(1, MOMENTUM_TOOL_ROUNDS + 1):
        # Only a transcript read justifies a longer answer (see _TRANSCRIPT_TOOLS).
        cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if transcript_used else MOMENTUM_MAX_TOKENS
        tool_choice = None
        if force_kb and not tools_used:
            tool_choice = {"type": "function", "function": {"name": "szukaj_w_bazie"}}
        resp = _chat(client, messages, max_tokens=cap, with_tools=True, tool_choice=tool_choice)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            content = (msg.content or "").strip()
            if content or resp.choices[0].finish_reason != "length":
                return content
            # Empty reply + finish_reason=length: the shared reasoning+reply budget
            # ran out before any visible text (gpt-5.2 reasoning tokens, or a long
            # requested answer, can eat the whole cap). This is NOT silence — retry
            # once with a much larger budget before giving up.
            logger.info(
                "Pusta odpowiedź przy finish_reason=length — ponawiam z budżetem %d",
                MOMENTUM_MAX_TOKENS_RETRY,
            )
            resp = _chat(
                client, messages, max_tokens=MOMENTUM_MAX_TOKENS_RETRY,
                with_tools=True, tool_choice=tool_choice,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return (msg.content or "").strip()
            # Retry pulled in a tool call — fall through to normal tool handling.
        tools_used = True
        transcript_used = transcript_used or any(
            tc.function.name in _TRANSCRIPT_TOOLS for tc in msg.tool_calls
        )
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
    cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if transcript_used else MOMENTUM_MAX_TOKENS
    resp = _chat(client, messages, max_tokens=cap, with_tools=False)
    return (resp.choices[0].message.content or "").strip()


def _generate_reply(user_msg: str, today_str: str, coaching: bool = False,
                    force_engage: bool = False, offer_coaching: bool = False) -> str:
    """Call OpenAI for the summon reply. Blocking — run via asyncio.to_thread.

    A synchronous client built from OPENAI_API_KEY (imported lazily so an unset
    key never breaks cog loading). MOMENTUM_USE_RESPONSES picks the transport:
    the Responses API (chained tool rounds, lower latency) or Chat Completions
    (current default). Both run the same tool loop and honour coaching mode
    (forced szukaj_w_bazie on the first round).

    ``force_engage`` (set for direct @mentions / DMs) injects a system-level
    override cancelling the [CISZA] licence so the model always replies.

    ``offer_coaching`` (set on ordinary, non-coaching summons) lets the model
    prepend a ``[COACHING?]`` sentinel to its reply when the question has real
    coaching potential — see ``COACHING_OFFER_INSTRUCTION``. Never combined
    with ``coaching=True`` (that path is already an explicit coaching request).
    """
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    if MOMENTUM_USE_RESPONSES:
        return _reply_via_responses(
            client, user_msg, today_str, coaching, force_engage, offer_coaching
        )
    return _reply_via_chat(client, user_msg, today_str, coaching, force_engage, offer_coaching)


async def _build_direct_user_msg(channel, bot_user_id: int) -> tuple[str, list[dict]]:
    """Fresh channel history → (prompt user-message, window), direct_mention=True.

    Shared by the coaching offer's two live regenerations (coaching pick, and
    the bare-sentinel edge case on "zwykła odpowiedź") so both read the
    channel's current state rather than the possibly-stale window from the
    original summon.
    """
    history = [m async for m in channel.history(limit=MOMENTUM_CONTEXT_MESSAGES)]
    history.reverse()
    window = _window_from_history(history)
    user_msg = build_summon_prompt(window, bot_user_id, direct_mention=True)
    return user_msg, window


class CoachingOfferView(discord.ui.View):
    """Offer shown under a summon reply flagged ``[COACHING?]`` by the model.

    All state lives on the instance (no cog-level dict, no DB) — an offer is
    lost on a bot restart, which is an acceptable trade-off for a UI nicety.
    ``regular_answer`` is the answer the model already produced alongside the
    flag, so picking "Zwykła odpowiedź" never needs a fresh LLM call. An
    ignored offer expires quietly (no answer dump — the asker walked away).
    """

    def __init__(self, cog: "Przywolanie", *, asker_id: int, is_owner: bool,
                 regular_answer: str, question: str):
        super().__init__(timeout=MOMENTUM_COACHING_OFFER_TIMEOUT)
        self.cog = cog
        self.asker_id = asker_id
        self.is_owner = is_owner
        self.regular_answer = regular_answer
        self.question = question
        self.message: discord.Message | None = None
        self._resolved = False  # guards the click-vs-timeout race

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.asker_id:
            return True
        await interaction.response.send_message(
            f"Ta propozycja jest dla <@{self.asker_id}> — to jego pytanie 🙂",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Zwykła odpowiedź", style=discord.ButtonStyle.secondary)
    async def regular(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._resolved = True
        self.stop()
        if self.regular_answer:
            await _edit_then_send_rest(
                interaction.message, self.regular_answer,
                edit=interaction.response.edit_message,
            )
            return
        # Edge case: the model returned a bare sentinel with no answer body.
        # Regenerate a guaranteed plain answer instead of leaving the user empty-handed.
        await interaction.response.defer(thinking=True)
        try:
            user_msg, window = await _build_direct_user_msg(
                interaction.channel, self.cog.bot.user.id
            )
            reply = await asyncio.to_thread(
                _generate_reply, user_msg, _today_key(), False, True, False
            )
            if not reply or reply == "[CISZA]":
                reply = (
                    "Jestem 👋 Doprecyzuj jednym zdaniem, o co pytasz, "
                    "to się do tego odniosę."
                )
            reply = repair_mentions(reply, window, self.cog.bot.user.id)
            await _send_reply(interaction.followup.send, reply)
        except Exception as e:
            logger.error("Błąd przy regeneracji zwykłej odpowiedzi (oferta coachingu): %s", e)
            import traceback

            traceback.print_exc()
            try:
                await interaction.followup.send(
                    "Coś poszło nie tak — spróbuj przywołać mnie jeszcze raz."
                )
            except Exception:
                pass

    @discord.ui.button(label="Tryb coachingowy", style=discord.ButtonStyle.primary, emoji="🧭")
    async def coaching(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.cog._coaching_quota_ok(self.asker_id, self.is_owner):
            self._resolved = True
            self.stop()
            logger.info("Miesięczny limit coachingu wyczerpany przez %s (oferta)", self.asker_id)
            await interaction.response.send_message(
                _coaching_limit_text(self.asker_id), ephemeral=True
            )
            await _edit_then_send_rest(
                interaction.message,
                self.regular_answer or "Oferta wygasła — zawołaj mnie jeszcze raz 🙂",
            )
            return

        self._resolved = True
        self.stop()
        # Edit within Discord's 3s interaction window, BEFORE the slow LLM call.
        await interaction.response.edit_message(
            content="Przechodzę w tryb coachingowy — daj mi chwilę… 🧭", view=None
        )
        try:
            logger.info(
                "Tryb coachingowy (oferta) na kanale %s przez %s",
                interaction.channel_id,
                self.asker_id,
            )
            user_msg, window = await _build_direct_user_msg(
                interaction.channel, self.cog.bot.user.id
            )
            user_msg += (
                f"\n\n{interaction.user.display_name} wybrał tryb coachingowy dla swojego "
                f"pytania: {self.question}"
            )
            reply = await asyncio.to_thread(_generate_reply, user_msg, _today_key(), True)
            if not reply or reply == "[CISZA]":
                reply = "Jestem. O czym chcesz pogadać w ramach coachingu?"

            reply = repair_mentions(reply, window, self.cog.bot.user.id)
            await _send_reply(interaction.followup.send, reply)
        except Exception as e:
            logger.error("Błąd w trybie coachingowym (oferta): %s", e)
            import traceback

            traceback.print_exc()
            try:
                await interaction.followup.send(
                    "Coś poszło nie tak przy coachingu — spróbuj ponownie za chwilę."
                )
            except Exception:
                pass

    async def on_timeout(self):
        if self._resolved:
            return
        try:
            if self.message is not None:
                await self.message.edit(
                    content="Oferta wygasła — zawołaj mnie, jak wrócisz 🙂",
                    view=None,
                )
        except discord.NotFound:
            pass


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
            # Only offer coaching on an ordinary summon — an explicit coaching
            # request is already the real thing, no need to ask twice.
            offer_eligible = MOMENTUM_COACHING_OFFER_ENABLED and not coaching

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
            window = _window_from_history(history)

            # A DM or an explicit @mention is addressed straight at the bot, so
            # drop the [CISZA] option — silence on a direct ping looks broken.
            # A bare-word "momentum" summon keeps it (may not be aimed at us).
            direct_mention = is_dm or bot_mentioned
            user_msg = build_summon_prompt(
                window, self.bot.user.id, direct_mention=direct_mention
            )
            # Show "Momentum pisze…" for the whole (possibly multi-round) call so a
            # slow reasoning/tool loop doesn't look like the bot froze.
            started = time.monotonic()
            async with message.channel.typing():
                reply = await asyncio.to_thread(
                    _generate_reply, user_msg, _today_key(), coaching, direct_mention,
                    offer_eligible,
                )
            logger.info(
                "Momentum odpowiedział w %.1fs (coaching=%s)",
                time.monotonic() - started,
                coaching,
            )
            if not reply or reply == "[CISZA]":
                # Log the summoning text (truncated) so a misfired silence on a
                # genuine question is diagnosable from the logs alone.
                logger.info(
                    "Model zwrócił ciszę (przywołanie: %.200r)", message.clean_content
                )
                # Safety net: a direct @mention/DM must never be met with silence.
                # If the model ignored the engage override and still returned
                # [CISZA], reply with a short clarifying nudge instead of nothing.
                if not direct_mention:
                    return
                logger.info("Bezpośrednie przywołanie + cisza — wysyłam dopytanie")
                reply = (
                    "Jestem 👋 Doprecyzuj jednym zdaniem, o co pytasz, "
                    "to się do tego odniosę."
                )

            offered, body = split_coaching_offer(reply)
            if offered and offer_eligible:
                answer = repair_mentions(body, window, self.bot.user.id)
                view = CoachingOfferView(
                    self, asker_id=message.author.id, is_owner=is_owner,
                    regular_answer=answer, question=message.clean_content,
                )
                view.message = await message.channel.send(
                    f"<@{message.author.id}>, to pytanie ma potencjał na coś więcej niż "
                    "szybka odpowiedź. Chcesz zwykłej odpowiedzi, czy przechodzimy w tryb "
                    "coachingowy? 🧭",
                    view=view,
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False, roles=False, users=True
                    ),
                )
                logger.info(
                    "Oferta coachingu dla %s na kanale %s", message.author.id, message.channel.id
                )
                return
            reply = body  # defensywnie usuwa zabłąkany sentinel nawet przy wyłączonej ofercie

            # Repair any '<Display Name>' pseudo-mention → real '<@id>' so pings work.
            reply = repair_mentions(reply, window, self.bot.user.id)
            await _send_reply(message.channel.send, reply)

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
            window = _window_from_history(history)

            # Slash /coaching-momentum is an explicit, deliberate invocation —
            # always engage (coaching mode already forbids [CISZA] too).
            user_msg = build_summon_prompt(window, self.bot.user.id, direct_mention=True)
            if temat:
                user_msg += (
                    f"\n\n{interaction.user.display_name} prosi o coaching na temat: {temat}"
                )
            reply = await asyncio.to_thread(_generate_reply, user_msg, _today_key(), True)
            if not reply or reply == "[CISZA]":
                reply = "Jestem. O czym chcesz pogadać w ramach coachingu?"

            reply = repair_mentions(reply, window, self.bot.user.id)
            await _send_reply(interaction.followup.send, reply)
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
