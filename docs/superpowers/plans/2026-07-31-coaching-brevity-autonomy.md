# Coaching Brevity & Autonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Momentum coaching replies become short (max 4 zdania + jeden ruch), stop arguing with a user's stated way of working, and the coaching offer expires quietly instead of guilt-tripping + dumping a lecture; a 30-min cooldown prevents re-offers in the same conversation.

**Architecture:** Prompt changes in `cogs/przywolanie.py` (SYSTEM_PROMPT section, COACHING_INSTRUCTION rewrite, COACHING_OFFER_INSTRUCTION sentence) + three small code changes: token-cap escalation restricted to transcript tools, quiet `on_timeout`, and an in-memory offer cooldown backed by a pure helper in `summon.py`.

**Tech Stack:** Python 3 / discord.py 2.7 / OpenAI Chat Completions & Responses. Tests: pytest, root-level `*_test.py`, bare `test_*` functions with plain asserts.

**Spec:** `docs/superpowers/specs/2026-07-31-coaching-brevity-autonomy-design.md`

## Global Constraints

- Polish user-facing copy; English allowed in code comments where existing file does the same (przywolanie.py mixes both — match surrounding lines).
- Conventional Commits, no Claude/Anthropic references in messages (GH-1, GH-2).
- Run tests with `python3 -m pytest summon_test.py greetings_test.py -q` from repo root `/Users/ludwikc/git/Momentum`.
- Byte-compile touched modules: `python3 -m py_compile cogs/przywolanie.py summon.py config.py`.
- `cogs/pomodoro.py` has an unrelated uncommitted modification — NEVER `git add -A`; stage explicit paths only.
- Do not change `MOMENTUM_MAX_TOKENS` (1000), `MOMENTUM_MAX_TOKENS_RETRY`, `MOMENTUM_TRANSCRIPT_MAX_TOKENS` (1500), `MOMENTUM_COACHING_OFFER_TIMEOUT` (120).

---

### Task 1: Pure cooldown helper `offer_allowed`

**Files:**
- Modify: `summon.py` (add function after `split_coaching_offer`, before `class DailyRateLimiter`)
- Test: `summon_test.py` (append a new section at end of file)

**Interfaces:**
- Produces: `offer_allowed(last_offer_ts: float | None, now: float, cooldown_s: float) -> bool` — imported by Task 5.

- [ ] **Step 1: Write the failing tests**

Append to `summon_test.py` (import `offer_allowed` by adding it to the existing `from summon import (...)` list, keeping alphabetical order — between `is_summon` and `repair_mentions`):

```python
# --- offer_allowed ------------------------------------------------------------

def test_offer_allowed_when_never_offered():
    assert offer_allowed(None, 100.0, 1800.0) is True


def test_offer_blocked_within_cooldown():
    assert offer_allowed(100.0, 1000.0, 1800.0) is False


def test_offer_allowed_at_and_after_cooldown():
    assert offer_allowed(100.0, 1900.0, 1800.0) is True
    assert offer_allowed(100.0, 5000.0, 1800.0) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest summon_test.py -q`
Expected: ImportError — `cannot import name 'offer_allowed' from 'summon'`

- [ ] **Step 3: Implement**

In `summon.py`, insert after the `split_coaching_offer` function body (after its `return True, m.group(1)` line and the blank lines that follow), before `class DailyRateLimiter`:

```python
def offer_allowed(last_offer_ts: float | None, now: float, cooldown_s: float) -> bool:
    """True when enough time passed since the last coaching offer to show a new one.

    ``last_offer_ts is None`` means no offer was ever shown to this
    (channel, user). Timestamps are monotonic-clock seconds
    (``time.monotonic()``), matching the cog's bookkeeping.
    """
    return last_offer_ts is None or (now - last_offer_ts) >= cooldown_s
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest summon_test.py -q`
Expected: all pass (37 existing + 3 new = 40)

- [ ] **Step 5: Commit**

```bash
git add summon.py summon_test.py
git commit -m "feat(przywolanie): add offer_allowed cooldown helper for coaching offers"
```

---

### Task 2: Prompt updates — autonomy section, coaching rewrite, offer guard

**Files:**
- Modify: `cogs/przywolanie.py` — `SYSTEM_PROMPT` (insert new section between "JAK SIĘ ODZYWASZ" and "JĘZYK"), `COACHING_INSTRUCTION` (full replacement), `COACHING_OFFER_INSTRUCTION` (one added sentence)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: prompt text only; no API changes.

- [ ] **Step 1: Insert the autonomy section into SYSTEM_PROMPT**

In `cogs/przywolanie.py`, find this exact fragment inside `SYSTEM_PROMPT` (end of the "JAK SIĘ ODZYWASZ" block):

```
- Zwracasz się do konkretnych osób po imieniu, używając podanych tokenów
  wzmianek. Wzmiankę wplatasz naturalnie w zdanie — NIE zawsze na początku.
  Raz na początku, raz w środku, raz na końcu, tak jak człowiek w rozmowie.

JĘZYK:
```

Replace with:

```
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
```

- [ ] **Step 2: Replace COACHING_INSTRUCTION**

Find (current full assignment):

```python
COACHING_INSTRUCTION = (
    "TRYB COACHINGU: rozmówca WPROST poprosił Cię o coaching. To jednoznaczne "
    "zaproszenie — NIE zwracasz [CISZA], zawsze się angażujesz. Oprzyj rozmowę na "
    "lekcjach z bazy wiedzy (właśnie je pobrałeś narzędziem szukaj_w_bazie). "
    "Prowadź konkretnie i z pewnością siebie (bliżej Jesse Eldera niż miękkiego "
    "coacha): postaw jasną, optymistyczną tezę i daj jeden konkretny krok do "
    "zrobienia; pytanie dodaj tylko, jeśli realnie popycha sprawę. Mówisz swoim "
    "głosem, po polsku i zwięźle — nie cytujesz lekcji sztywno."
)
```

Replace with:

```python
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
```

- [ ] **Step 3: Extend COACHING_OFFER_INSTRUCTION**

Find the fragment inside `COACHING_OFFER_INSTRUCTION`:

```python
    "dodajesz TYLKO przy realnym potencjale coachingowym — nigdy przy pogawędce, "
    "powitaniach, pytaniach o fakty/spotkania/sprawy techniczne. Nigdy nie "
    "wspominaj o tym tokenie w treści odpowiedzi."
```

Replace with:

```python
    "dodajesz TYLKO przy realnym potencjale coachingowym — nigdy przy pogawędce, "
    "powitaniach, pytaniach o fakty/spotkania/sprawy techniczne. Nie dodawaj go "
    "też, gdy w oknie rozmowy już trwa Twoja coachingowa wymiana z tą osobą "
    "albo niedawno jej to proponowałeś. Nigdy nie wspominaj o tym tokenie w "
    "treści odpowiedzi."
```

- [ ] **Step 4: Byte-compile**

Run: `python3 -m py_compile cogs/przywolanie.py`
Expected: no output, exit 0

- [ ] **Step 5: Commit**

```bash
git add cogs/przywolanie.py
git commit -m "feat(przywolanie): coaching max 4 zdania, szanuj sposób pracy rozmówcy

Feedback z rozmowy z użytkowniczką: odpowiedzi coachingowe były
wielopunktowymi wykładami, bot trzykrotnie renegocjował jej własny plan
pracy, a rozmowa zabierała czas zamiast pchać do działania.

- SYSTEM_PROMPT: nowa sekcja AUTONOMIA ROZMÓWCY I KONIEC ROZMOWY
  (challenge raz, potem wspieraj; sygnał wyjścia = jedno zdanie, zero
  pytań; sukces = powrót do działania)
- COACHING_INSTRUCTION: twardy limit 4 zdań + jeden ruch, zakaz
  numerowanych planów bez prośby
- COACHING_OFFER_INSTRUCTION: nie flaguj [COACHING?] w trwającej
  wymianie coachingowej"
```

---

### Task 3: Token cap — only transcript tools escalate the budget

**Files:**
- Modify: `cogs/przywolanie.py` — module constant near `_TOOLS_RESPONSES`, both reply loops (`_reply_via_responses`, `_reply_via_chat`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `_TRANSCRIPT_TOOLS: set[str]` module constant (internal).

- [ ] **Step 1: Add the constant**

In `cogs/przywolanie.py`, find:

```python
# The same tools in the Responses API's flat shape (no nested "function" key).
# Derived from _TOOLS so the definitions live in one place.
_TOOLS_RESPONSES = [{"type": "function", **t["function"]} for t in _TOOLS]
```

Replace with:

```python
# The same tools in the Responses API's flat shape (no nested "function" key).
# Derived from _TOOLS so the definitions live in one place.
_TOOLS_RESPONSES = [{"type": "function", **t["function"]} for t in _TOOLS]

# Tools whose output justifies a longer reply (full meeting transcripts).
# szukaj_w_bazie is deliberately NOT here: KB-grounded coaching answers must
# stay on the short budget — brevity is part of the persona, and the transcript
# cap applied to coaching was how replies ballooned into essays.
_TRANSCRIPT_TOOLS = {"lista_spotkan", "czytaj_spotkanie"}
```

- [ ] **Step 2: Rework `_reply_via_responses`**

Find:

```python
    inp = user_msg          # first turn: the summon prompt as plain user input
    previous_id = None
    tools_used = False
    for round_idx in range(1, MOMENTUM_TOOL_ROUNDS + 1):
        cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if tools_used else MOMENTUM_MAX_TOKENS
```

Replace with:

```python
    inp = user_msg          # first turn: the summon prompt as plain user input
    previous_id = None
    tools_used = False
    transcript_used = False
    for round_idx in range(1, MOMENTUM_TOOL_ROUNDS + 1):
        cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if transcript_used else MOMENTUM_MAX_TOKENS
```

Then find (in the same function, after the retry block):

```python
        tools_used = True
        logger.info(
            "Momentum tool-loop runda %d/%d: %s",
            round_idx, MOMENTUM_TOOL_ROUNDS, [name for _, name, _ in calls],
        )
```

Replace with:

```python
        tools_used = True
        transcript_used = transcript_used or any(
            name in _TRANSCRIPT_TOOLS for _, name, _ in calls
        )
        logger.info(
            "Momentum tool-loop runda %d/%d: %s",
            round_idx, MOMENTUM_TOOL_ROUNDS, [name for _, name, _ in calls],
        )
```

Then find the post-loop fallback in the same function:

```python
    # Tool budget exhausted — force a final answer from what we've gathered.
    resp = _respond(
        client, instructions=instructions, input=inp,
        max_output_tokens=MOMENTUM_TRANSCRIPT_MAX_TOKENS, with_tools=False,
        previous_id=previous_id,
    )
    return (resp.output_text or "").strip()
```

Replace with:

```python
    # Tool budget exhausted — force a final answer from what we've gathered.
    cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if transcript_used else MOMENTUM_MAX_TOKENS
    resp = _respond(
        client, instructions=instructions, input=inp,
        max_output_tokens=cap, with_tools=False,
        previous_id=previous_id,
    )
    return (resp.output_text or "").strip()
```

- [ ] **Step 3: Rework `_reply_via_chat`**

Find:

```python
    tools_used = False
    for round_idx in range(1, MOMENTUM_TOOL_ROUNDS + 1):
        # Once a tool has been pulled in, allow a longer answer.
        cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if tools_used else MOMENTUM_MAX_TOKENS
```

Replace with:

```python
    tools_used = False
    transcript_used = False
    for round_idx in range(1, MOMENTUM_TOOL_ROUNDS + 1):
        # Only a transcript read justifies a longer answer (see _TRANSCRIPT_TOOLS).
        cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if transcript_used else MOMENTUM_MAX_TOKENS
```

Then find (in the same function):

```python
        tools_used = True
        logger.info(
            "Momentum tool-loop runda %d/%d: %s",
            round_idx,
            MOMENTUM_TOOL_ROUNDS,
            [tc.function.name for tc in msg.tool_calls],
        )
```

Replace with:

```python
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
```

Then find the post-loop fallback in the same function:

```python
    # Tool budget exhausted — force a final answer from what we've gathered.
    resp = _chat(client, messages, max_tokens=MOMENTUM_TRANSCRIPT_MAX_TOKENS, with_tools=False)
    return (resp.choices[0].message.content or "").strip()
```

Replace with:

```python
    # Tool budget exhausted — force a final answer from what we've gathered.
    cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if transcript_used else MOMENTUM_MAX_TOKENS
    resp = _chat(client, messages, max_tokens=cap, with_tools=False)
    return (resp.choices[0].message.content or "").strip()
```

- [ ] **Step 4: Verify**

Run: `python3 -m py_compile cogs/przywolanie.py && python3 -m pytest summon_test.py greetings_test.py -q`
Expected: compile OK, all tests pass

- [ ] **Step 5: Commit**

```bash
git add cogs/przywolanie.py
git commit -m "fix(przywolanie): podbijaj budżet odpowiedzi tylko przy transkrypcjach

Każde użycie narzędzia (w tym szukaj_w_bazie w trybie coachingu)
eskalowało cap do MOMENTUM_TRANSCRIPT_MAX_TOKENS (1500) — stąd
coachingowe ściany tekstu. Teraz eskalują tylko lista_spotkan /
czytaj_spotkanie; coaching zostaje na MOMENTUM_MAX_TOKENS."
```

---

### Task 4: Quiet coaching-offer timeout

**Files:**
- Modify: `cogs/przywolanie.py` — `CoachingOfferView` docstring + `on_timeout`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: no API changes.

- [ ] **Step 1: Update the class docstring**

Find:

```python
    All state lives on the instance (no cog-level dict, no DB) — an offer is
    lost on a bot restart, which is an acceptable trade-off for a UI nicety.
    ``regular_answer`` is the answer the model already produced alongside the
    flag, so picking "Zwykła odpowiedź" (or letting the offer time out) never
    needs a fresh LLM call.
    """
```

Replace with:

```python
    All state lives on the instance (no cog-level dict, no DB) — an offer is
    lost on a bot restart, which is an acceptable trade-off for a UI nicety.
    ``regular_answer`` is the answer the model already produced alongside the
    flag, so picking "Zwykła odpowiedź" never needs a fresh LLM call. An
    ignored offer expires quietly (no answer dump — the asker walked away).
    """
```

- [ ] **Step 2: Replace `on_timeout`**

Find:

```python
    async def on_timeout(self):
        if self._resolved:
            return
        note = (
            "Nie odpowiadasz, więc pewnie masz inne tematy na głowie — tutaj "
            '"zwykła" odpowiedź ;)\n\n' + self.regular_answer
            if self.regular_answer
            else "Oferta wygasła — zawołaj mnie jeszcze raz 🙂"
        )
        try:
            if self.message is not None:
                await _edit_then_send_rest(self.message, note)
        except discord.NotFound:
            pass
```

Replace with:

```python
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
```

- [ ] **Step 3: Verify**

Run: `python3 -m py_compile cogs/przywolanie.py`
Expected: no output, exit 0

- [ ] **Step 4: Commit**

```bash
git add cogs/przywolanie.py
git commit -m "fix(przywolanie): oferta coachingu wygasa cicho, bez wykładu

Timeout edytował ofertę na pasywno-agresywne \"Nie odpowiadasz...\"
i zrzucał pełną przygotowaną odpowiedź osobie, która już wyszła.
Teraz: krótkie wygaśnięcie z zaproszeniem do ponownego zawołania."
```

---

### Task 5: 30-min offer cooldown per (channel, user)

**Files:**
- Modify: `config.py` (new constant), `cogs/przywolanie.py` (imports, `__init__`, `on_message`)

**Interfaces:**
- Consumes: `offer_allowed(last_offer_ts, now, cooldown_s)` from Task 1.
- Produces: `MOMENTUM_COACHING_OFFER_COOLDOWN_S = 1800` config constant.

- [ ] **Step 1: Add the config constant**

In `config.py`, find:

```python
MOMENTUM_COACHING_OFFER_ENABLED = True
MOMENTUM_COACHING_OFFER_TIMEOUT = 120
```

Replace with:

```python
MOMENTUM_COACHING_OFFER_ENABLED = True
MOMENTUM_COACHING_OFFER_TIMEOUT = 120
# Po pokazaniu oferty nie ponawiaj jej temu samemu userowi w tym samym kanale
# przez tyle sekund — druga oferta w trwającej rozmowie to szum (in-memory,
# zeruje się przy restarcie, jak DailyRateLimiter).
MOMENTUM_COACHING_OFFER_COOLDOWN_S = 1800
```

- [ ] **Step 2: Extend the imports in `cogs/przywolanie.py`**

Find:

```python
    MOMENTUM_COACHING_OFFER_ENABLED,
    MOMENTUM_COACHING_OFFER_TIMEOUT,
```

Replace with:

```python
    MOMENTUM_COACHING_OFFER_COOLDOWN_S,
    MOMENTUM_COACHING_OFFER_ENABLED,
    MOMENTUM_COACHING_OFFER_TIMEOUT,
```

Then find:

```python
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
```

Replace with:

```python
from summon import (
    DailyRateLimiter,
    build_summon_prompt,
    extract_tool_calls,
    is_coaching_request,
    is_param_compat_error,
    is_summon,
    offer_allowed,
    repair_mentions,
    split_coaching_offer,
    split_for_discord,
)
```

- [ ] **Step 3: Track offer timestamps in the cog**

Find:

```python
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rate_limiter = DailyRateLimiter(MOMENTUM_DAILY_LIMIT)
        logger.info("Przywolanie cog initialized")
```

Replace with:

```python
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rate_limiter = DailyRateLimiter(MOMENTUM_DAILY_LIMIT)
        # (channel_id, user_id) -> time.monotonic() of the last coaching offer,
        # so an ongoing conversation isn't re-offered coaching every summon.
        self._offer_last: dict[tuple[int, int], float] = {}
        logger.info("Przywolanie cog initialized")
```

- [ ] **Step 4: Gate `offer_eligible` on the cooldown**

Find:

```python
            coaching = is_coaching_request(message.content)
            # Only offer coaching on an ordinary summon — an explicit coaching
            # request is already the real thing, no need to ask twice.
            offer_eligible = MOMENTUM_COACHING_OFFER_ENABLED and not coaching
```

Replace with:

```python
            coaching = is_coaching_request(message.content)
            # Only offer coaching on an ordinary summon — an explicit coaching
            # request is already the real thing, no need to ask twice. A fresh
            # offer is also suppressed while a recent one for this (channel,
            # user) is still within the cooldown window.
            offer_eligible = (
                MOMENTUM_COACHING_OFFER_ENABLED
                and not coaching
                and offer_allowed(
                    self._offer_last.get((message.channel.id, message.author.id)),
                    time.monotonic(),
                    MOMENTUM_COACHING_OFFER_COOLDOWN_S,
                )
            )
```

- [ ] **Step 5: Record the timestamp when an offer is posted**

Find:

```python
                logger.info(
                    "Oferta coachingu dla %s na kanale %s", message.author.id, message.channel.id
                )
                return
```

Replace with:

```python
                self._offer_last[(message.channel.id, message.author.id)] = (
                    time.monotonic()
                )
                logger.info(
                    "Oferta coachingu dla %s na kanale %s", message.author.id, message.channel.id
                )
                return
```

- [ ] **Step 6: Verify**

Run: `python3 -m py_compile cogs/przywolanie.py config.py && python3 -m pytest summon_test.py greetings_test.py -q`
Expected: compile OK, all tests pass

- [ ] **Step 7: Commit**

```bash
git add config.py cogs/przywolanie.py
git commit -m "feat(przywolanie): cooldown 30 min na ponowną ofertę coachingu

Druga oferta trybu coachingowego potrafiła wyskoczyć kilka minut po
pierwszej, w środku tej samej rozmowy (każdy summon jest bezstanowy).
Teraz oferta per (kanał, user) ma 30-minutowy cooldown (in-memory,
offer_allowed z summon.py)."
```

---

### Task 6: Docs — CLAUDE.md changelog

**Files:**
- Modify: `CLAUDE.md` (repo root — section `## Changelog`, subsection `**2026-07**`)

**Interfaces:** none.

- [ ] **Step 1: Add the changelog bullet**

In `/Users/ludwikc/git/Momentum/CLAUDE.md`, add as the FIRST bullet under the `**2026-07**` heading (read the file first — origin/main may have reworded the section; keep the existing style):

```markdown
- **Coaching: krótkie strzały + autonomia rozmówcy** (feedback z porannej rozmowy
  na Deep Work; spec: `docs/superpowers/specs/2026-07-31-coaching-brevity-autonomy-design.md`):
  odpowiedzi coachingowe max 4 zdania + jeden ruch (twardy limit w promptcie;
  cap 1500 tokenów podbijają już tylko narzędzia transkrypcji, nie
  `szukaj_w_bazie`); nowa sekcja SYSTEM_PROMPT „AUTONOMIA ROZMÓWCY I KONIEC
  ROZMOWY" (challenge raz, potem wspieraj plan usera; „znikam/idę działać" =
  jedno zdanie pożegnania, zero pytań); oferta coachingu wygasa cicho (koniec
  „Nie odpowiadasz…" + dumpa odpowiedzi) i ma 30-min cooldown per (kanał, user)
  (`MOMENTUM_COACHING_OFFER_COOLDOWN_S`, `offer_allowed` w `summon.py`).
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: changelog — coaching brevity, autonomia rozmówcy, cooldown oferty"
```

---

## Deploy (manual, after merge)

On the server (`/root/Momentum`), per CLAUDE.md "Running & restarting":

```bash
git pull
venv/bin/python -m py_compile cogs/przywolanie.py summon.py config.py
kill $(cat bot.pid)
nohup venv/bin/python main.py >> bot.log 2>&1 &
echo $! > bot.pid
```

Then confirm in `bot.log`: "Przywolanie cog initialized", "Synced N commands", no traceback.

**Live smoke test:** summon with coaching potential → offer appears → click 🧭 → reply ≤4 sentences; second summon in the same conversation → no second offer; ignore an offer → after 120 s it collapses to "Oferta wygasła — zawołaj mnie, jak wrócisz 🙂" with no lecture.
