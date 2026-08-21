# Weekly Daily-Coaching Digest DM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Friday 14:00 (Warsaw) the bot DMs the owner a ready-to-paste #ogłoszenia
announcement — a weekly summary of the 12:34 Daily Coaching meetings, written in Ludwik's
announcement voice (rewriter-discord patterns), tagging `@LIFEHACKERZY`.

**Architecture:** Pure prompt-building module `digest.py` (mirrors the `summon.py` pattern:
testable logic outside the cog) + new cog `cogs/weekly_digest.py` (1-minute `tasks.loop`
firing Friday 14:00 Warsaw with a once-per-day guard, exactly like `daily_invite`; plus an
owner-only `/podsumowanie-tygodnia` slash command that triggers the same DM on demand for
testing). Data source: the existing local transcripts store (`transcripts.list_transcripts`
+ `read_transcript`), filtered to the Daily Coaching channel. Generation: one OpenAI call
(`MOMENTUM_MODEL`) with the announcement-voice system prompt embedded in `digest.py`
(condensed verbatim from `~/.claude/skills/rewriter-discord/` SKILL.md + wzorce-ogloszen.md).

**Tech Stack:** Python 3.10 (VPS venv), discord.py 2.7, stdlib `unittest`, OpenAI SDK
(already a dependency), `pytz` for Warsaw time (repo convention in cogs).

## Global Constraints

- Commit messages: Conventional Commits, **never** mention Claude/Anthropic (CLAUDE.md GH-1/GH-2).
- User-facing strings in Polish; code/comments in English.
- Tests: stdlib `unittest` only, in `tests/test_*.py`, **must NOT import `discord`** (not installed on the dev Mac). Known local-only failure to ignore: `tests/test_activity_embed.py` (`ModuleNotFoundError: No module named 'discord'`) — passes on the VPS venv.
- `cogs/*.py` cannot be imported locally; gate is `python3 -m py_compile <file>`.
- All schedule math in Europe/Warsaw.
- Deploy only in the final task, on the `mikrus` VPS.

## Facts the tasks rely on

- Owner id constant: `config.MOMENTUM_OWNER_ID` (= 404038151565213696). Model constant: `config.MOMENTUM_MODEL` (= "gpt-5.2"; rejects `max_tokens`/non-default `temperature`, accepts `max_completion_tokens`).
- `transcripts.list_transcripts(within_days=N)` → newest-first `[{id, data: "YYYY-MM-DD HH:MM", kanal, uczestnicy: [str]}]`; `transcripts.read_transcript(id) -> Optional[str]` (diarized Markdown body).
- Daily Coaching transcripts have `kanal` containing `1234-daily-coaching` (older files: bare slug; newer: `🔢│1234-daily-coaching`).
- `summon.split_for_discord(text) -> list[str]` splits long messages for Discord's 2000-char cap.
- Loop pattern to copy: `cogs/daily_invite.py` (1-min loop, `now.strftime("%H:%M") != TIME` + `_last_sent_date` guard, `before_loop` waits for ready).
- `main.py` `EXTENSIONS` list ends with `"cogs.admin_task"` around line 157.

---

### Task 1: `digest.py` — pure selection + prompt building + DM text

**Files:**
- Create: `digest.py`
- Create: `tests/test_digest.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces (used by Task 2's cog):
  - `select_daily_meetings(items: list[dict], *, channel_key: str) -> list[dict]` — keeps items whose `kanal` contains `channel_key`, preserving input order.
  - `build_digest_messages(meetings: list[dict], *, week_label: str) -> tuple[str, str]` — `(system_prompt, user_prompt)`; each meeting dict has keys `data`, `uczestnicy` (list[str]), `body` (str, pre-truncated by caller).
  - `build_dm_text(post: str) -> str` — wraps the generated post for the owner DM (intro line + ```markdown code block + placeholder checklist when `[LINK]` present).

- [ ] **Step 1: Write the failing test**

Create `tests/test_digest.py`:

```python
import unittest

from digest import build_digest_messages, build_dm_text, select_daily_meetings


class SelectDailyMeetingsTest(unittest.TestCase):
    ITEMS = [
        {"id": "a", "data": "2026-08-07 12:34", "kanal": "🔢│1234-daily-coaching", "uczestnicy": ["A"]},
        {"id": "b", "data": "2026-08-05 06:31", "kanal": "warsztaty-lifehackerow", "uczestnicy": ["B"]},
        {"id": "c", "data": "2026-08-04 12:35", "kanal": "1234-daily-coaching", "uczestnicy": ["C"]},
    ]

    def test_keeps_only_daily_coaching_in_order(self):
        got = select_daily_meetings(self.ITEMS, channel_key="1234-daily-coaching")
        self.assertEqual([m["id"] for m in got], ["a", "c"])

    def test_empty_input(self):
        self.assertEqual(select_daily_meetings([], channel_key="x"), [])


class BuildDigestMessagesTest(unittest.TestCase):
    MEETINGS = [
        {"data": "2026-08-04 12:35", "uczestnicy": ["Ala", "Ola"], "body": "**Ala:** gadamy o nawykach"},
        {"data": "2026-08-07 12:34", "uczestnicy": ["Ala"], "body": "**Ala:** upały i produktywność"},
    ]

    def test_system_prompt_carries_style_anchors(self):
        system, _ = build_digest_messages(self.MEETINGS, week_label="03.08–09.08")
        for anchor in ("@LIFEHACKERZY", "Wy/Was/Wam", "[LINK]", "WYŁĄCZNIE gotowy post"):
            self.assertIn(anchor, system)

    def test_user_prompt_carries_meetings_and_label(self):
        _, user = build_digest_messages(self.MEETINGS, week_label="03.08–09.08")
        self.assertIn("03.08–09.08", user)
        self.assertIn("2026-08-04 12:35", user)
        self.assertIn("Ala, Ola", user)
        self.assertIn("upały i produktywność", user)


class BuildDmTextTest(unittest.TestCase):
    def test_wraps_post_in_code_block(self):
        dm = build_dm_text("@LIFEHACKERZY\n## Tydzień rozkminek\n- bullet")
        self.assertIn("```markdown\n@LIFEHACKERZY", dm)
        self.assertTrue(dm.rstrip().endswith("```"))

    def test_lists_link_placeholder_when_present(self):
        dm = build_dm_text("@LIFEHACKERZY\n## X\n- y\n\n[LINK]")
        self.assertIn("[LINK]", dm.split("```")[-1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_digest -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'digest'`

- [ ] **Step 3: Write minimal implementation**

Create `digest.py`:

```python
# digest.py
# Pure logic for the weekly Daily-Coaching digest DM (cogs/weekly_digest.py):
# meeting selection, the announcement-voice prompt, and the DM wrapper.
# Voice rules condensed from Ludwik's rewriter-discord skill (SKILL.md +
# wzorce-ogloszen.md) — the generated post must be indistinguishable from an
# announcement Ludwik writes himself on #ogłoszenia.
# Pure stdlib, no discord/openai imports — unit-testable (same split as summon.py).

# The system prompt is the style contract. Keep the anchors tested in
# tests/test_digest.py ("@LIFEHACKERZY", "Wy/Was/Wam", "[LINK]",
# "WYŁĄCZNIE gotowy post") intact when editing.
DIGEST_SYSTEM_PROMPT = """Piszesz ogłoszenie na kanał #ogłoszenia społeczności \
Lifehackerzy — cotygodniowe podsumowanie spotkań Daily Coaching (codziennie o 12:34). \
Piszesz głosem Ludwika, nieodróżnialnie od jego własnych postów.

STRUKTURA (dokładnie w tej kolejności):
@LIFEHACKERZY
## <tytuł 2–5 słów, bez kropki>
- bullety
(pusta linia)
<jedna linia zamknięcia>
[LINK]

REGUŁY STYLU (każda obowiązuje, bez wyjątku):
- Wy/Was/Wam/Wasze zawsze wielką literą; ton „my, nasza ekipa"
- bullety zaczynają się małą literą i nie mają kropki na końcu (pełnozdaniowy bullet
  wyjątkowo może skończyć się kropką lub wykrzyknikiem)
- bullety RÓŻNEJ długości — 3 słowa obok 12, rytm mówiony, nie tabelka; łącznie 5–9
- **bold** na daty, godziny i fakty nośne; _kursywa_ na tytuły/cytaty
- emoji: zero albo pojedynczy akcent; wykrzykniki 1–3 na post; CAPS pojedynczych słów
  (MEGA, SUPER, BARDZO) dla emfazy
- daty w formacie 23.10, godziny 12:34, kanały jako #nazwa-kanału, osoby jako @Imię
- słownik Ludwika: rozkminka, protip, przypominajka, spotkanko, Platforma (wielką),
  mega/super/turbo/ultra-, „jak zwykle", „koniecznie", „już niedługo", stay tuned
- zamknięcie jedną krótką linią, np.: Do zobaczenia! · Dzięki, że tutaj jesteście ·
  Udanego tygodnia · Ja będę, a Wy? · Wpadacie? · Dzięki raz jeszcze!
- ZAKAZ: korpomowa, „Szanowni Państwo", „Mam nadzieję, że…", „Podsumowując",
  idealnie równoległe bullety tej samej długości, ściana emoji, fabrykowana pilność

TREŚĆ (szablon podsumowania tygodnia):
- otwarcie: ile spotkań było w tym tygodniu / tydzień pełen rozkminek
- 3–6 bulletów z NAJCIEKAWSZYMI tematami tygodnia — konkrety z transkryptów, nie
  ogólniki; wpleć **dni tygodnia lub daty**
- wyróżnienie najaktywniejszych: 2–4 osoby najczęściej obecne, jako @Imię
- zaproszenie na kolejny tydzień: jak zwykle codziennie o **12:34** na #1234-daily-coaching
- ostatnia linia postu: [LINK] (placeholder na link do nagrań na Platformie)

KOTWICA — prawdziwy post Ludwika tego typu (podsumowanie po spotkaniu):
@LIFEHACKERZY
## Pierwsze spotkanie drugiej edycji @Grupa: BookClubPL
- pierwsze spotkanie właśnie się zakończyło
- bardzo dziękuję Wam za obecność
- szczególne podziękowania dla najaktywniejszych
- i jednocześnie z włączonymi kamerkami
- @Anka & @Jakub Pjanka - widzę Was!
- ustaliliśmy, że kolejne spotkanie już za tydzień, tj. **22.12 o 12:30**
- nagranie spotkania już jest dostępne na Platformie:

https://platform.siadlak.com/products/...

Dzięki raz jeszcze!

ZWRÓĆ WYŁĄCZNIE gotowy post — bez komentarzy, bez omawiania, bez bloków kodu."""


def select_daily_meetings(items: list[dict], *, channel_key: str) -> list[dict]:
    """Keep only meetings whose channel contains ``channel_key``, in input order.

    Transcript frontmatter stores the channel two ways ("1234-daily-coaching"
    for recovered files, "🔢│1234-daily-coaching" for live ones) — substring
    match covers both.
    """
    return [m for m in items if channel_key in (m.get("kanal") or "")]


def build_digest_messages(meetings: list[dict], *, week_label: str) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for the weekly digest LLM call.

    ``meetings`` are chronological dicts with data/uczestnicy/body; bodies are
    already truncated by the caller (the cog owns size budgeting).
    """
    parts = [f"Tydzień {week_label}. Spotkania Daily Coaching z tego tygodnia:"]
    for m in meetings:
        who = ", ".join(m.get("uczestnicy") or []) or "(nieznani)"
        parts.append(
            f"=== Spotkanie {m.get('data', '?')} | uczestnicy: {who} ===\n"
            f"{(m.get('body') or '').strip()}"
        )
    return DIGEST_SYSTEM_PROMPT, "\n\n".join(parts)


def build_dm_text(post: str) -> str:
    """Wrap the generated announcement for the owner DM: intro, copy-paste
    code block, and a to-fill checklist when the [LINK] placeholder is used."""
    dm = (
        "Piątkowa przypominajka 📋 — wzór ogłoszenia z podsumowaniem tygodnia "
        "Daily Coaching, gotowy do wklejenia na #ogłoszenia:\n"
        f"```markdown\n{post.strip()}\n```"
    )
    if "[LINK]" in post:
        dm += "\nDo uzupełnienia przed publikacją: `[LINK]` — link do nagrań na Platformie."
    return dm
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_digest -v`
Expected: 6 tests PASS. Then full suite `python3 -m unittest discover tests` — green except the known `test_activity_embed` local import error.

- [ ] **Step 5: Commit**

```bash
git add digest.py tests/test_digest.py
git commit -m "feat(digest): pure prompt/selection helpers for weekly coaching digest"
```

---

### Task 2: `cogs/weekly_digest.py` + config + EXTENSIONS + docs

**Files:**
- Create: `cogs/weekly_digest.py`
- Modify: `config.py` (append a Weekly digest section)
- Modify: `main.py` (append to `EXTENSIONS`)
- Modify: `CLAUDE.md` (cog table, config table, background-tasks line, changelog)

**Interfaces:**
- Consumes: `digest.select_daily_meetings`, `digest.build_digest_messages`, `digest.build_dm_text` (Task 1); `transcripts.list_transcripts`, `transcripts.read_transcript`; `summon.split_for_discord`; config constants below.
- Produces: cog `WeeklyDigest` with `tasks.loop` `schedule_digest` (1 min) and slash `/podsumowanie-tygodnia` (owner-only).

- [ ] **Step 1: Add config constants**

Append to `config.py` (after the Momentum/przywołanie section, matching its comment style):

```python
# --- Weekly Daily-Coaching digest DM (cogs/weekly_digest.py) ---
WEEKLY_DIGEST_ENABLED = True
WEEKLY_DIGEST_WEEKDAY = 4        # Monday=0 … Friday=4 (Warsaw)
WEEKLY_DIGEST_TIME = "14:00"     # Warsaw wall-clock, checked once a minute
WEEKLY_DIGEST_LOOKBACK_DAYS = 7  # meetings window fed into the digest
WEEKLY_DIGEST_CHANNEL_KEY = "1234-daily-coaching"  # kanal substring filter
WEEKLY_DIGEST_PER_MEETING_CHARS = 8000  # per-transcript cap fed to the model
WEEKLY_DIGEST_MAX_TOKENS = 2000  # completion budget for the announcement
```

- [ ] **Step 2: Create the cog**

Create `cogs/weekly_digest.py`:

```python
"""Weekly Daily-Coaching digest: every Friday 14:00 (Warsaw) DM the owner a
ready-to-paste #ogłoszenia announcement summarizing the week's 12:34 meetings.

Data: local transcripts store (transcripts.py). Voice: digest.DIGEST_SYSTEM_PROMPT
(condensed rewriter-discord patterns). One OpenAI call per digest, off-thread,
same lazy-client pattern as transcribe.py/przywolanie.py. The slash command
/podsumowanie-tygodnia (owner-only) triggers the same DM on demand — the test
path that doesn't wait for Friday.
"""
import asyncio
import datetime
import logging
import os

import discord
import pytz
from discord import app_commands
from discord.ext import commands, tasks

import digest
import transcripts
from config import (
    MOMENTUM_MODEL,
    MOMENTUM_OWNER_ID,
    WEEKLY_DIGEST_CHANNEL_KEY,
    WEEKLY_DIGEST_ENABLED,
    WEEKLY_DIGEST_LOOKBACK_DAYS,
    WEEKLY_DIGEST_MAX_TOKENS,
    WEEKLY_DIGEST_PER_MEETING_CHARS,
    WEEKLY_DIGEST_TIME,
    WEEKLY_DIGEST_WEEKDAY,
)
from summon import split_for_discord

logger = logging.getLogger("momentum_bot.weekly_digest")


def _generate_post(system_prompt: str, user_prompt: str) -> str:
    """One chat completion for the digest. Blocking — call via asyncio.to_thread.

    MOMENTUM_MODEL (gpt-5.2) rejects max_tokens/non-default temperature, so we
    send max_completion_tokens from the start and never touch temperature.
    """
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=MOMENTUM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=WEEKLY_DIGEST_MAX_TOKENS,
    )
    return (resp.choices[0].message.content or "").strip()


class WeeklyDigest(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.warsaw = pytz.timezone("Europe/Warsaw")
        self._last_sent_date = None  # once-per-day guard, daily_invite pattern
        logger.info("WeeklyDigest cog initialized")

    @commands.Cog.listener()
    async def on_ready(self):
        if WEEKLY_DIGEST_ENABLED and not self.schedule_digest.is_running():
            self.schedule_digest.start()
            logger.info(
                "Weekly digest scheduled: weekday=%s %s (Warsaw)",
                WEEKLY_DIGEST_WEEKDAY, WEEKLY_DIGEST_TIME,
            )

    def cog_unload(self):
        if self.schedule_digest.is_running():
            self.schedule_digest.cancel()

    @tasks.loop(minutes=1)
    async def schedule_digest(self):
        now = datetime.datetime.now(self.warsaw)
        if (now.weekday() != WEEKLY_DIGEST_WEEKDAY
                or now.strftime("%H:%M") != WEEKLY_DIGEST_TIME
                or self._last_sent_date == now.date()):
            return
        self._last_sent_date = now.date()
        try:
            await self._send_digest()
        except Exception:
            logger.exception("Weekly digest failed")

    @schedule_digest.before_loop
    async def before_schedule_digest(self):
        await self.bot.wait_until_ready()

    async def _send_digest(self) -> str:
        """Collect the week's meetings, generate the announcement, DM the owner.

        Returns a short status string (also used by the slash command reply).
        Every degraded path still sends a DM — a silent Friday looks broken.
        """
        owner = await self.bot.fetch_user(MOMENTUM_OWNER_ID)
        now = datetime.datetime.now(self.warsaw)
        week_label = f"{(now - datetime.timedelta(days=6)):%d.%m}–{now:%d.%m}"

        items = await asyncio.to_thread(
            transcripts.list_transcripts, WEEKLY_DIGEST_LOOKBACK_DAYS
        )
        meetings = digest.select_daily_meetings(
            items, channel_key=WEEKLY_DIGEST_CHANNEL_KEY
        )
        meetings.reverse()  # list_transcripts is newest-first; digest reads chronologically

        if not meetings:
            await owner.send(
                f"📋 Piątkowe podsumowanie ({week_label}): w tym tygodniu nie mam "
                "żadnych transkryptów z Daily Coaching — nie ma z czego złożyć ogłoszenia."
            )
            return "brak spotkań"

        if not os.getenv("OPENAI_API_KEY"):
            days = ", ".join(m["data"][:10] for m in meetings)
            await owner.send(
                f"📋 Piątkowe podsumowanie ({week_label}): mam {len(meetings)} "
                f"transkryptów ({days}), ale brak OPENAI_API_KEY — nie wygeneruję wzoru."
            )
            return "brak klucza OpenAI"

        enriched = []
        for m in meetings:
            body = await asyncio.to_thread(transcripts.read_transcript, m["id"])
            if not body:
                continue
            enriched.append({
                "data": m["data"],
                "uczestnicy": m.get("uczestnicy") or [],
                "body": body[:WEEKLY_DIGEST_PER_MEETING_CHARS],
            })
        if not enriched:
            await owner.send(
                f"📋 Piątkowe podsumowanie ({week_label}): transkrypty z tego "
                "tygodnia są puste/nieczytelne — nie wygeneruję wzoru."
            )
            return "puste transkrypty"

        system_prompt, user_prompt = digest.build_digest_messages(
            enriched, week_label=week_label
        )
        post = await asyncio.to_thread(_generate_post, system_prompt, user_prompt)
        if not post:
            await owner.send(
                f"📋 Piątkowe podsumowanie ({week_label}): model zwrócił pustą "
                "odpowiedź — spróbuj ponownie przez /podsumowanie-tygodnia."
            )
            return "pusta odpowiedź modelu"

        for chunk in split_for_discord(digest.build_dm_text(post)):
            await owner.send(chunk)
        logger.info("Weekly digest DM sent (%d meetings, %s)", len(enriched), week_label)
        return f"wysłane ({len(enriched)} spotkań)"

    @app_commands.command(
        name="podsumowanie-tygodnia",
        description="(owner) Wyślij mi DM z wzorem cotygodniowego ogłoszenia Daily Coaching.",
    )
    async def podsumowanie_tygodnia(self, interaction: discord.Interaction):
        if interaction.user.id != MOMENTUM_OWNER_ID:
            await interaction.response.send_message(
                "Ta komenda jest tylko dla właściciela bota.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            status = await self._send_digest()
            await interaction.followup.send(f"Gotowe — {status}. Sprawdź DM 📬")
        except Exception as e:
            logger.exception("Digest via slash failed")
            await interaction.followup.send(f"Nie wyszło: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(WeeklyDigest(bot))
```

- [ ] **Step 3: Register the extension**

In `main.py`, append after the `"cogs.admin_task"` line in `EXTENSIONS`:

```python
    "cogs.weekly_digest",  # piątkowy DM z wzorem ogłoszenia-podsumowania Daily Coaching
```

- [ ] **Step 4: Compile-check + full suite**

Run: `python3 -m py_compile cogs/weekly_digest.py config.py main.py digest.py && python3 -m unittest discover tests`
Expected: silent compile; suite green except the known `test_activity_embed` local import error.

- [ ] **Step 5: Update CLAUDE.md**

1. Cog table — append row after `admin_task` (28):

```markdown
| 29 | `weekly_digest` | Piątek 14:00: DM do ownera z gotowym wzorem ogłoszenia-podsumowania tygodnia Daily Coaching (głos Ludwika wg rewriter-discord, tag @LIFEHACKERZY, transkrypty z 7 dni przez gpt) | `/podsumowanie-tygodnia` (owner); tasks.loop 1m |
```

2. Config table — append rows after the `VOICE_RANKS` row:

```markdown
| `WEEKLY_DIGEST_ENABLED` / `_WEEKDAY` / `_TIME` | `True` / `4` / `"14:00"` | Piątkowy digest DM (Warsaw) |
| `WEEKLY_DIGEST_LOOKBACK_DAYS` / `_CHANNEL_KEY` / `_PER_MEETING_CHARS` / `_MAX_TOKENS` | `7` / `"1234-daily-coaching"` / `8000` / `2000` | Zakres i budżety digestu |
```

3. Background tasks line (Commands/listeners/tasks reference) — extend with `· weekly_digest 1m`.

4. Slash-commands line — add `/podsumowanie-tygodnia` (owner) next to `/admin-task`.

5. Changelog — add at the top of `**2026-08**`:

```markdown
- **Piątkowy digest Daily Coaching** — nowy cog `weekly_digest`: w każdy piątek
  o 14:00 (Warsaw) owner dostaje DM z gotowym do wklejenia wzorem ogłoszenia
  na #ogłoszenia (tag @LIFEHACKERZY, głos Ludwika wg skilla rewriter-discord —
  reguły stylu wbudowane w `digest.DIGEST_SYSTEM_PROMPT`), złożonym przez
  gpt z transkryptów 12:34 z ostatnich 7 dni (`digest.py` — czyste helpery
  z testami; ścieżki awaryjne zawsze wysyłają DM z diagnozą). Test na żądanie:
  `/podsumowanie-tygodnia` (owner-only). Config: `WEEKLY_DIGEST_*`.
```

- [ ] **Step 6: Commit**

```bash
git add cogs/weekly_digest.py config.py main.py CLAUDE.md
git commit -m "feat(digest): piątkowy DM z wzorem ogłoszenia-podsumowania Daily Coaching

Nowy cog weekly_digest: pętla 1m (piątek 14:00 Warsaw, guard raz dziennie)
+ /podsumowanie-tygodnia (owner) do testu na żądanie. Transkrypty 12:34
z 7 dni -> gpt z wbudowanym głosem ogłoszeń -> DM z postem w bloku kodu
i listą placeholderów. Ścieżki awaryjne (brak spotkań/klucza/pustka)
zawsze wysyłają DM z diagnozą."
```

---

### Task 3: deploy to mikrus + verify (MAIN THREAD — not a subagent)

- [ ] **Step 1: Push** (`git push` from main after merge)

- [ ] **Step 2: Deploy**

```bash
ssh mikrus "cd /home/ludwikc/Momentum && sudo -u ludwikc git pull && venv/bin/python -m py_compile main.py config.py digest.py cogs/weekly_digest.py && venv/bin/python -m unittest discover tests && systemctl restart momentum-bot && systemctl is-active momentum-bot"
```

Expected: suite `OK` (venv has discord), `active`.

- [ ] **Step 3: Verify startup**

```bash
ssh mikrus "journalctl -u momentum-bot --since '2 minutes ago' | grep -a 'weekly_digest\|Synced\|Traceback' | head"
```

Expected: `WeeklyDigest cog initialized`, `Weekly digest scheduled: weekday=4 14:00 (Warsaw)`, `Synced N commands` with N one higher than before, no Traceback.

- [ ] **Step 4: Dry-run the generation on the VPS (no Discord, no DM)**

```bash
ssh mikrus "cd /home/ludwikc/Momentum && venv/bin/python - << 'EOF'
import asyncio, datetime, pytz
from dotenv import load_dotenv; load_dotenv()
import digest, transcripts
from cogs.weekly_digest import _generate_post
now = datetime.datetime.now(pytz.timezone('Europe/Warsaw'))
items = transcripts.list_transcripts(within_days=7)
meetings = digest.select_daily_meetings(items, channel_key='1234-daily-coaching')
meetings.reverse()
enriched = [{'data': m['data'], 'uczestnicy': m['uczestnicy'],
             'body': (transcripts.read_transcript(m['id']) or '')[:8000]} for m in meetings]
s, u = digest.build_digest_messages(enriched, week_label='dry-run')
print(_generate_post(s, u))
EOF"
```

Expected: a Polish announcement starting with `@LIFEHACKERZY`, `## title`, varied bullets, closing line, `[LINK]` — eyeball it against the rewriter-discord core rules.

- [ ] **Step 5: End-to-end** — the owner runs `/podsumowanie-tygodnia` on Discord and confirms the DM arrives with the post in a code block. (Slash commands sync per-guild — available within a minute of restart.)

---

## Self-Review (done at plan time)

- **Spec coverage:** Friday 14:00 DM ✔ (loop + config), announcement pattern per fresh rewriter-discord ✔ (DIGEST_SYSTEM_PROMPT condensed from SKILL.md + wzorce-ogloszen.md read this session), group tagging ✔ (@LIFEHACKERZY per the reference's tag table for daily coaching; participants as @Imię), on-demand test path ✔ (/podsumowanie-tygodnia), degraded paths always DM ✔.
- **Placeholders:** none — full code and doc text inline.
- **Type consistency:** `select_daily_meetings(items, *, channel_key)` and `build_digest_messages(meetings, *, week_label) -> tuple[str, str]` match between digest.py, tests, and the cog; `read_transcript(id) -> Optional[str]` handled (`if not body: continue`); `split_for_discord(text) -> list[str]` used for DM chunks.
