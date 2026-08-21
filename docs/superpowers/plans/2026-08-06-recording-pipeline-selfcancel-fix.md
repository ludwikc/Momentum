# Recording Pipeline Self-Cancel Fix + Orphan Recovery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recordings that hit the 120-min safety cap (or die in a restart) currently lose their
transcript, Drive upload and notification silently — fix the root-cause self-cancel bug, recover
the orphaned WAVs already sitting on the VPS, and make the publish pipeline impossible to kill
silently again.

**Architecture:** Root cause: `_safety_stop` (running inside `self._safety_task`) awaits
`_finish_and_publish`, which awaits `_teardown`, which calls `self._safety_task.cancel()` —
cancelling the very task executing the pipeline. `CancelledError` fires at the next await
(`asyncio.sleep(0.5)` in `_teardown`) and everything downstream (transcode → Whisper →
`save_transcript` → Drive upload → notify) silently never runs. Fix = a guarded cancel helper
(`taskutil.cancel_unless_current`) + clearing the task handle before the safety path enters the
pipeline. Recovery = on startup, detect WAVs in `recordings/` with no matching transcript (pure
helpers in `parsers.py`/`transcripts.py`, unit-tested) and run the missing pipeline steps for
each. Hardening = exception/cancel logging wrapper around the pipeline + mod-channel alert,
cap raised to 180 min (warsztaty run >2h), full-datetime sort in `list_transcripts`.

**Tech Stack:** Python 3.10 (VPS venv), discord.py 2.7, stdlib `unittest`
(`python3 -m unittest discover tests`), ffmpeg, OpenAI Whisper via `transcribe.py`,
Google Drive via `gdrive.py`.

## Global Constraints

- Commit messages: Conventional Commits (`fix:`, `feat:`, `test:`, `docs:`…), **never** mention Claude/Anthropic (CLAUDE.md GH-1/GH-2).
- User-facing strings in Polish; code/comments in English (repo convention).
- Tests: stdlib `unittest` only, live in `tests/test_*.py`, import project modules top-level (`from parsers import …`), run from repo root with `python3 -m unittest discover tests`.
- **Tests must NOT import `discord`** (not installed on the dev Mac). Pre-existing known local failure: `tests/test_activity_embed.py` errors locally with `ModuleNotFoundError: No module named 'discord'` — ignore it; it passes on the VPS venv. "Suite green" locally = every test except that one import error.
- `cogs/voicerecord.py` cannot be unit-tested locally (imports discord/voice_recv); verify edits with `python3 -m py_compile cogs/voicerecord.py` — which **works locally** because py_compile only compiles, it does not import.
- Timezone: filenames/timestamps are Warsaw-local.
- Do NOT run the bot locally. Deploy happens only in the final task, on the `mikrus` VPS.

## Production facts the tasks rely on

- Repo on VPS: `/home/ludwikc/Momentum`, service `momentum-bot.service`, venv at `venv/`.
- Orphaned files currently in `/home/ludwikc/Momentum/recordings/`:
  - `Lifehackerzy_2026-07-23-12-34-46_1234-daily-coaching_497188.wav` (209 MB, no diarization sidecar)
  - `Lifehackerzy_2026-07-28-06-30-40_warsztaty-lifehackerow_961c1e.wav` (168 MB) + `…961c1e.wav.diarization.json`
  - Legacy junk: `recording_2026-06-22_21-50-06.wav` (0 B), `recording_2026-06-22_21-09-55.mp3` (813 B) — non-conforming names, recovery must skip them.
- Transcript filenames: `<YYYY-MM-DD>_<HH-MM>_<slug>_<rec_id>.md`; recording filenames: `Lifehackerzy_<YYYY-MM-DD-HH-MM-SS>_<slug>_<rec_id>.wav`. The shared `rec_id` (6 hex chars) is the join key.

---

### Task 1: `taskutil.cancel_unless_current` + self-cancel fix in voicerecord

**Files:**
- Create: `taskutil.py`
- Create: `tests/test_taskutil.py`
- Modify: `cogs/voicerecord.py` (`_safety_stop` ~line 198, `_teardown` ~line 208)

**Interfaces:**
- Consumes: nothing new.
- Produces: `taskutil.cancel_unless_current(task: asyncio.Task | None) -> None` — cancels the task unless it is the currently running task (or None). Used by `_teardown`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_taskutil.py`:

```python
import asyncio
import unittest

from taskutil import cancel_unless_current


class CancelUnlessCurrentTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancels_a_different_task(self):
        async def sleeper():
            await asyncio.sleep(30)

        task = asyncio.create_task(sleeper())
        await asyncio.sleep(0)  # let it start
        cancel_unless_current(task)
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_does_not_cancel_the_calling_task(self):
        # Regression for the safety-cap bug: the safety task ran the publish
        # pipeline itself; teardown cancelling it killed the pipeline at its
        # next await. With the guard, the pipeline finishes.
        finished = []

        async def pipeline():
            cancel_unless_current(asyncio.current_task())
            await asyncio.sleep(0)  # a naive task.cancel() would explode here
            finished.append(True)

        await asyncio.create_task(pipeline())
        self.assertEqual(finished, [True])

    async def test_none_is_a_no_op(self):
        self.assertIsNone(cancel_unless_current(None))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_taskutil -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'taskutil'`

- [ ] **Step 3: Write minimal implementation**

Create `taskutil.py`:

```python
"""Small asyncio task helpers shared by cogs."""
import asyncio


def cancel_unless_current(task: asyncio.Task | None) -> None:
    """Cancel ``task`` unless it is the task calling us (or None).

    ``task.cancel()`` on the *currently running* task raises CancelledError at
    its next await — a teardown helper invoked from within that task would kill
    its own caller's remaining pipeline. That is exactly how every recording
    that hit the safety cap lost its transcript/upload: the safety task ran the
    publish pipeline, teardown cancelled the safety task, boom. Guarding here
    keeps teardown safe to call from any task, including the guarded one.
    """
    if task is not None and task is not asyncio.current_task():
        task.cancel()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_taskutil -v`
Expected: 3 tests PASS

- [ ] **Step 5: Apply the fix in `cogs/voicerecord.py`**

Add the import after the existing `from mixsink import MixingWaveSink` line (~line 21):

```python
from mixsink import MixingWaveSink
from taskutil import cancel_unless_current
```

Replace `_safety_stop` (currently lines 198–206):

```python
    async def _safety_stop(self):
        """Auto-stop after the configured cap so a forgotten recording can't run forever."""
        try:
            await asyncio.sleep(RECORDING_MAX_MINUTES * 60)
        except asyncio.CancelledError:
            return
        if self.recording:
            logger.info("Safety cap reached (%s min) — stopping recording", RECORDING_MAX_MINUTES)
            # This task now runs the publish pipeline itself. Clear the handle
            # first so _teardown can't cancel the very task executing it —
            # that self-cancel silently killed every ≥cap recording's
            # transcript/upload before this guard existed.
            self._safety_task = None
            await self._finish_and_publish(reason="limit czasu")
```

In `_teardown`, replace:

```python
        if self._safety_task:
            self._safety_task.cancel()
            self._safety_task = None
```

with:

```python
        if self._safety_task:
            cancel_unless_current(self._safety_task)
            self._safety_task = None
```

- [ ] **Step 6: Compile-check + full local suite**

Run: `python3 -m py_compile cogs/voicerecord.py taskutil.py && python3 -m unittest discover tests`
Expected: py_compile silent; suite = only the pre-existing `test_activity_embed` import error, everything else PASS.

- [ ] **Step 7: Commit**

```bash
git add taskutil.py tests/test_taskutil.py cogs/voicerecord.py
git commit -m "fix(voicerecord): safety-cap stop cancelled its own publish pipeline

_safety_stop awaited _finish_and_publish from inside self._safety_task;
_teardown then cancelled that task, so CancelledError fired at the next
await and transcode/Whisper/transcript/Drive/notify never ran — every
recording hitting the 120-min cap (all warsztaty) vanished silently and
the stuck recording state blocked auto-record until the next restart.
Guard the cancel (taskutil.cancel_unless_current) and clear the handle
before the safety path enters the pipeline."
```

---

### Task 2: `parsers.parse_recording_filename`

**Files:**
- Modify: `parsers.py` (append at end; reuse existing `re`, `datetime`, `Optional` imports — check the file header and add any of these that are missing)
- Modify: `tests/test_parsers.py` (append a new TestCase class)

**Interfaces:**
- Consumes: nothing new.
- Produces: `parse_recording_filename(name: str) -> Optional[tuple[datetime, str, str]]` — `(started, channel_slug, rec_id)` for recorder-produced filenames, `None` otherwise. Used by `transcripts.find_orphans` (Task 4) and the recovery cog code (Task 5).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_parsers.py` (add `parse_recording_filename` to the existing `from parsers import (…)` block):

```python
class TestParseRecordingFilename(unittest.TestCase):
    def test_wav_filename_parses(self):
        got = parse_recording_filename(
            "Lifehackerzy_2026-07-28-06-30-40_warsztaty-lifehackerow_961c1e.wav"
        )
        self.assertEqual(
            got,
            (datetime(2026, 7, 28, 6, 30, 40), "warsztaty-lifehackerow", "961c1e"),
        )

    def test_mp3_filename_parses(self):
        got = parse_recording_filename(
            "Lifehackerzy_2026-07-23-12-34-46_1234-daily-coaching_497188.mp3"
        )
        self.assertEqual(
            got,
            (datetime(2026, 7, 23, 12, 34, 46), "1234-daily-coaching", "497188"),
        )

    def test_legacy_and_sidecar_names_return_none(self):
        for name in (
            "recording_2026-06-22_21-50-06.wav",
            "Lifehackerzy_2026-07-28-06-30-40_warsztaty-lifehackerow_961c1e.wav.diarization.json",
            "notes.txt",
            "",
            None,
        ):
            self.assertIsNone(parse_recording_filename(name), name)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_parsers -v`
Expected: ImportError — `cannot import name 'parse_recording_filename'`

- [ ] **Step 3: Write minimal implementation**

Append to `parsers.py`:

```python
_RECORDING_FILENAME_RE = re.compile(
    r"^Lifehackerzy_(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})_(.+)_([0-9a-f]{6})\.(wav|mp3)$"
)


def parse_recording_filename(name: str) -> Optional[tuple[datetime, str, str]]:
    """Split a recorder filename into (started, channel_slug, rec_id).

    The voice recorder names files
    ``Lifehackerzy_<YYYY-MM-DD-HH-MM-SS>_<slug>_<rec_id>.wav`` (Warsaw-local
    clock). Anything else — legacy files, diarization sidecars — returns None.
    Slugs never contain underscores (see voicerecord.slug_channel_name), so the
    greedy middle group cannot swallow the rec_id.
    """
    m = _RECORDING_FILENAME_RE.match(name or "")
    if not m:
        return None
    try:
        started = datetime.strptime(m.group(1), "%Y-%m-%d-%H-%M-%S")
    except ValueError:
        return None
    return started, m.group(2), m.group(3)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_parsers -v`
Expected: all PASS (existing + 3 new)

- [ ] **Step 5: Commit**

```bash
git add parsers.py tests/test_parsers.py
git commit -m "feat(parsers): parse_recording_filename — recorder file -> (started, slug, rec_id)"
```

---

### Task 3: full-datetime sort in `transcripts.list_transcripts`

**Files:**
- Modify: `transcripts.py` (`_date_of` stays; add `_datetime_of`; adjust `list_transcripts` lines ~117–128)
- Create: `tests/test_transcripts.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_datetime_of(s: str) -> Optional[datetime]` (module-private, tested); `list_transcripts` now sorts same-day meetings newest-first by time (was: day-granularity, filesystem-order ties).

- [ ] **Step 1: Write the failing test**

Create `tests/test_transcripts.py`:

```python
import tempfile
import unittest
from datetime import date, datetime

import transcripts
from transcripts import _datetime_of


class DatetimeOfTest(unittest.TestCase):
    def test_frontmatter_format(self):
        self.assertEqual(_datetime_of("2026-08-04 12:34"), datetime(2026, 8, 4, 12, 34))

    def test_filename_stem_format(self):
        self.assertEqual(_datetime_of("2026-08-04_12-34"), datetime(2026, 8, 4, 12, 34))

    def test_date_only_falls_back_to_midnight(self):
        self.assertEqual(_datetime_of("2026-08-04"), datetime(2026, 8, 4))

    def test_garbage_returns_none(self):
        self.assertIsNone(_datetime_of("nie-data"))
        self.assertIsNone(_datetime_of(""))


class ListTranscriptsOrderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = transcripts.TRANSCRIPTS_DIR
        transcripts.TRANSCRIPTS_DIR = self._tmp.name

    def tearDown(self):
        transcripts.TRANSCRIPTS_DIR = self._orig
        self._tmp.cleanup()

    def test_same_day_meetings_sort_newest_first(self):
        transcripts.save_transcript(
            "**A:** rano", started=datetime(2026, 8, 4, 6, 31),
            channel_name="warsztaty", rec_id="aaaaaa",
        )
        transcripts.save_transcript(
            "**B:** poludnie", started=datetime(2026, 8, 4, 12, 34),
            channel_name="daily", rec_id="bbbbbb",
        )
        items = transcripts.list_transcripts(today=date(2026, 8, 4))
        self.assertEqual(
            [i["id"] for i in items],
            ["2026-08-04_12-34_daily_bbbbbb", "2026-08-04_06-31_warsztaty_aaaaaa"],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_transcripts -v`
Expected: ImportError — `cannot import name '_datetime_of'`. (The ordering test alone would be
flaky-red — old code ties same-day entries and order falls to `os.listdir` — which is why the
red gate is the `_datetime_of` import, deterministic on every filesystem.)

- [ ] **Step 3: Write minimal implementation**

In `transcripts.py`, add below the existing `_date_of` function:

```python
def _datetime_of(s: str) -> Optional[datetime]:
    """Parse 'YYYY-MM-DD HH:MM' (frontmatter) or 'YYYY-MM-DD_HH-MM' (filename
    stem); date-only strings fall back to midnight via _date_of."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d_%H-%M"):
        try:
            return datetime.strptime((s or "")[:16], fmt)
        except (ValueError, TypeError):
            continue
    d = _date_of(s)
    return datetime(d.year, d.month, d.day) if d else None
```

In `list_transcripts`, replace:

```python
        data_str = meta.get("data", "")
        d = _date_of(data_str) or _date_of(fname[:10])
        if within_days is not None and d is not None and (today - d).days > within_days:
            continue
        out.append({
            "id": meta.get("id") or fname[:-3],
            "data": data_str or fname[:10],
            "kanal": meta.get("kanal", "?"),
            "uczestnicy": [p.strip() for p in meta.get("uczestnicy", "").split(",") if p.strip()],
            "_sort": d or date.min,
        })
    out.sort(key=lambda m: m["_sort"], reverse=True)
```

with:

```python
        data_str = meta.get("data", "")
        dt = _datetime_of(data_str) or _datetime_of(fname)
        d = dt.date() if dt else None
        if within_days is not None and d is not None and (today - d).days > within_days:
            continue
        out.append({
            "id": meta.get("id") or fname[:-3],
            "data": data_str or fname[:10],
            "kanal": meta.get("kanal", "?"),
            "uczestnicy": [p.strip() for p in meta.get("uczestnicy", "").split(",") if p.strip()],
            "_sort": dt or datetime.min,
        })
    # Full datetime (minute precision), id as deterministic tiebreak — two
    # same-day meetings previously tied on the date and fell to listdir order.
    out.sort(key=lambda m: (m["_sort"], m["id"]), reverse=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_transcripts -v`
Expected: all PASS. Also run the full suite: `python3 -m unittest discover tests` — only the pre-existing `test_activity_embed` import error remains.

- [ ] **Step 5: Commit**

```bash
git add transcripts.py tests/test_transcripts.py
git commit -m "fix(transcripts): sort meetings by full datetime, not day

Two same-day meetings tied on the date-only sort key and their order fell
to os.listdir — 'ostatnie spotkanie' could resolve to the morning workshop
instead of the noon daily. Minute precision + id tiebreak."
```

---

### Task 4: `transcripts.find_orphans` — WAVs with no transcript

**Files:**
- Modify: `transcripts.py` (add import + function)
- Modify: `tests/test_transcripts.py` (append TestCase)

**Interfaces:**
- Consumes: `parsers.parse_recording_filename` (Task 2).
- Produces: `find_orphans(recording_names: list[str], transcript_names: list[str]) -> list[str]` — pure: filenames in, orphaned `.wav` filenames out. Used by the recovery cog code (Task 5).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_transcripts.py` (extend the import line to `from transcripts import _datetime_of, find_orphans`):

```python
class FindOrphansTest(unittest.TestCase):
    RECORDINGS = [
        "Lifehackerzy_2026-07-28-06-30-40_warsztaty-lifehackerow_961c1e.wav",
        "Lifehackerzy_2026-07-28-06-30-40_warsztaty-lifehackerow_961c1e.wav.diarization.json",
        "Lifehackerzy_2026-08-06-12-34-01_1234-daily-coaching_c26abe.wav",
        "recording_2026-06-22_21-50-06.wav",  # legacy junk — never an orphan
        "Lifehackerzy_2026-07-23-12-34-46_1234-daily-coaching_497188.mp3",  # mp3 ≠ orphan
    ]
    TRANSCRIPTS = [
        "2026-08-06_12-34_1234-daily-coaching_c26abe.md",
        "2026-07-07_06-32_warsztaty-lifehacker-w_57010a.md",
    ]

    def test_wav_without_transcript_is_orphan(self):
        self.assertEqual(
            find_orphans(self.RECORDINGS, self.TRANSCRIPTS),
            ["Lifehackerzy_2026-07-28-06-30-40_warsztaty-lifehackerow_961c1e.wav"],
        )

    def test_empty_inputs(self):
        self.assertEqual(find_orphans([], []), [])
        self.assertEqual(find_orphans([], self.TRANSCRIPTS), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_transcripts -v`
Expected: ImportError — `cannot import name 'find_orphans'`

- [ ] **Step 3: Write minimal implementation**

In `transcripts.py`, add to the imports (top of file):

```python
from parsers import parse_recording_filename
```

Add the function after `list_transcripts`:

```python
def find_orphans(recording_names: list[str], transcript_names: list[str]) -> list[str]:
    """WAV recordings that never got a transcript.

    A crash/restart mid-recording (or, historically, the safety-cap self-cancel
    bug) leaves a closed WAV in recordings/ with no .md in transcripts/ — the
    meeting silently drops out of Momentum's memory. The shared rec_id filename
    suffix is the join key; non-recorder names (legacy files, sidecars) are
    ignored. Pure: filename lists in, orphaned .wav names out.
    """
    have = {
        t[:-3].rsplit("_", 1)[-1]
        for t in transcript_names
        if t.endswith(".md")
    }
    out = []
    for r in recording_names:
        if not r.endswith(".wav"):
            continue
        parsed = parse_recording_filename(r)
        if parsed is not None and parsed[2] not in have:
            out.append(r)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_transcripts -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add transcripts.py tests/test_transcripts.py
git commit -m "feat(transcripts): find_orphans — detect recordings that never got a transcript"
```

---

### Task 5: startup orphan recovery in voicerecord

**Files:**
- Modify: `cogs/voicerecord.py` (`__init__` ~line 105, `on_ready` ~line 130, new methods after `_transcode_to_mp3` ~line 251)

**Interfaces:**
- Consumes: `transcripts.find_orphans` (Task 4), `parsers.parse_recording_filename` (Task 2), existing `self._transcode_to_mp3`, `transcribe.is_configured/transcribe_words`, `self._build_transcript`, `transcripts.save_transcript`, `gdrive.is_configured/upload_file/local_md5`, `self._upload_transcript`, `self._notify`.
- Produces: `async _recover_orphans(self)` and `async _publish_recovered(self, wav_path, started, channel_slug, rec_id)` — internal to the cog; `on_ready` schedules `_recover_orphans` once per process.

- [ ] **Step 1: Add the import**

In `cogs/voicerecord.py`, the `import parsers`-style import is not present; add to the existing project-imports block (after `import transcripts`):

```python
from parsers import parse_recording_filename
```

- [ ] **Step 2: Add the once-flag in `__init__`**

After the line `self._lock = asyncio.Lock()` add:

```python
        # One orphan-recovery pass per process (on_ready re-fires on reconnects).
        self._recovery_ran = False
```

- [ ] **Step 3: Schedule recovery in `on_ready`**

Replace the body of `on_ready`:

```python
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.auto_sweep.is_running():
            self.auto_sweep.start()
        if not self._recovery_ran:
            self._recovery_ran = True
            asyncio.create_task(self._recover_orphans())
        logger.info("VoiceRecord cog is ready (auto-record: %s, channels: %s)",
                    AUTO_RECORD_ENABLED, AUTO_RECORD_CHANNEL_IDS)
```

- [ ] **Step 4: Add the recovery methods**

Insert after `_transcode_to_mp3` (before `_finish_and_publish`):

```python
    async def _recover_orphans(self):
        """Finish the publish pipeline for recordings that never got one.

        A crash/restart mid-recording (or the pre-fix safety-cap self-cancel)
        leaves a closed WAV with no transcript — the meeting silently vanishes
        from Momentum's memory. Run the missing transcode → transcribe → save →
        upload steps for each orphan, oldest first. Best-effort per file: one
        failure never blocks the next, and a failed WAV stays on disk for the
        next startup's retry.
        """
        try:
            rec_names = os.listdir(RECORDINGS_DIR)
        except OSError:
            return
        try:
            tr_names = os.listdir(transcripts.TRANSCRIPTS_DIR)
        except OSError:
            tr_names = []
        orphans = sorted(transcripts.find_orphans(rec_names, tr_names))
        if not orphans:
            return
        logger.info("Orphaned recordings to recover: %s", orphans)
        for fname in orphans:
            wav_path = os.path.join(RECORDINGS_DIR, fname)
            if wav_path == self.wav_path:
                continue  # an active recording is not an orphan
            parsed = parse_recording_filename(fname)
            if parsed is None:
                continue
            started, slug, rec_id = parsed
            try:
                await self._publish_recovered(wav_path, started, slug, rec_id)
            except Exception:
                logger.exception("Recovery failed for %s", fname)

    async def _publish_recovered(self, wav_path: str, started: datetime,
                                 channel_slug: str, rec_id: str):
        """Transcode/transcribe/save/upload one orphaned WAV (see _recover_orphans).

        Mirrors the live pipeline minus the parts that need live state: no
        thank-you, no summary post (participants unknown, meeting long past) —
        the goal is the transcript back in Momentum's memory and the audio on
        Drive. The WAV is deleted only once its content is safe (transcript
        saved, or transcription unconfigured), so a transient failure retries
        on the next startup.
        """
        mp3_path = await self._transcode_to_mp3(wav_path)
        if mp3_path is None:
            await self._notify(
                f"⚠️ Odzyskiwanie nagrania `{rec_id}` nie powiodło się "
                f"(transkodowanie) — plik zostaje: `{wav_path}`"
            )
            return
        transcript = None
        saved = False
        if transcribe.is_configured():
            try:
                text, words = await asyncio.to_thread(transcribe.transcribe_words, mp3_path)
                transcript = self._build_transcript(text, words, wav_path)
                if transcript:
                    saved = bool(await asyncio.to_thread(
                        transcripts.save_transcript, transcript,
                        started=started, channel_name=channel_slug, rec_id=rec_id,
                    ))
            except Exception as e:
                logger.error("Recovery transcription failed for %s: %s", rec_id, e)
        if saved or not transcribe.is_configured():
            try:
                os.remove(wav_path)
            except OSError:
                pass
        msg = (f"♻️ Odzyskane nagranie z **#{channel_slug}** "
               f"({started.strftime('%Y-%m-%d %H:%M')})")
        if gdrive.is_configured():
            try:
                info = await asyncio.to_thread(
                    gdrive.upload_file, mp3_path, os.path.basename(mp3_path)
                )
                msg += f": {info.get('webViewLink')}"
                if transcript:
                    await self._upload_transcript(mp3_path, transcript)
                remote_md5 = info.get("md5Checksum")
                local_md5 = await asyncio.to_thread(gdrive.local_md5, mp3_path)
                if remote_md5 and remote_md5 == local_md5:
                    try:
                        os.remove(mp3_path)
                    except OSError:
                        pass
                else:
                    msg += (f"\n⚠️ Nie udało się zweryfikować kopii na Drive — "
                            f"lokalna kopia: `{mp3_path}`")
            except Exception as e:
                logger.error("Recovery Drive upload failed for %s: %s", rec_id, e)
                msg += f" — upload na Drive nie powiódł się, plik lokalnie: `{mp3_path}`"
        else:
            msg += f" — zapisane lokalnie: `{mp3_path}`"
        if saved:
            msg += "\n📝 Transkrypcja odzyskana — Momentum znów pamięta to spotkanie."
        elif transcribe.is_configured():
            msg += "\n⚠️ Transkrypcja się nie udała — WAV zostaje do ponownej próby przy następnym starcie."
        await self._notify(msg)
```

- [ ] **Step 5: Compile-check + full local suite**

Run: `python3 -m py_compile cogs/voicerecord.py && python3 -m unittest discover tests`
Expected: py_compile silent; suite green except the pre-existing `test_activity_embed` import error.

- [ ] **Step 6: Commit**

```bash
git add cogs/voicerecord.py
git commit -m "feat(voicerecord): recover orphaned recordings on startup

Scan recordings/ for WAVs with no matching transcript (rec_id join) and
run the missing transcode -> Whisper -> save_transcript -> Drive steps.
Recovers the meetings lost to the safety-cap self-cancel (warsztaty
2026-07-28, daily 2026-07-23) and any future crash mid-recording."
```

---

### Task 6: hardening — pipeline error reporting, cap 180 min, docs

**Files:**
- Modify: `cogs/voicerecord.py` (`_finish_and_publish` ~line 253)
- Modify: `config.py` (`RECORDING_MAX_MINUTES`)
- Modify: `CLAUDE.md` (config table, known issues, changelog)

**Interfaces:**
- Consumes: existing `_finish_and_publish` body, `self._notify`.
- Produces: `_finish_and_publish` keeps its exact signature (`reason=None, *, suppress_auto=False) -> str`) — all 5 call sites unchanged; the old body moves to `_publish_pipeline` (same signature).

- [ ] **Step 1: Wrap the publish pipeline**

In `cogs/voicerecord.py`, rename the existing method line:

```python
    async def _finish_and_publish(self, reason: str | None = None, *, suppress_auto: bool = False) -> str:
```

to:

```python
    async def _publish_pipeline(self, reason: str | None = None, *, suppress_auto: bool = False) -> str:
```

(keep its docstring and entire body untouched), then insert this new method directly above it:

```python
    async def _finish_and_publish(self, reason: str | None = None, *, suppress_auto: bool = False) -> str:
        """Guarded wrapper around the publish pipeline.

        The pipeline runs from fire-and-forget tasks (safety stop, voice-state
        handlers) whose exceptions vanish — the July 2026 self-cancel silently
        ate three weeks of warsztaty. Log every death loudly and tell the mod
        channel; the WAV stays on disk and startup recovery picks it up.
        """
        rec_id = self.rec_id
        try:
            return await self._publish_pipeline(reason, suppress_auto=suppress_auto)
        except asyncio.CancelledError:
            logger.error("Publish pipeline CANCELLED mid-flight (rec_id=%s)", rec_id)
            raise
        except Exception:
            logger.exception("Publish pipeline failed (rec_id=%s)", rec_id)
            msg = (f"⚠️ Publikacja nagrania `{rec_id}` nie powiodła się — audio "
                   "zostało w recordings/, odzyskam je przy następnym starcie.")
            try:
                await self._notify(msg)
            except Exception:
                pass
            return msg
```

- [ ] **Step 2: Raise the cap**

In `config.py` change:

```python
RECORDING_MAX_MINUTES = 120
```

to:

```python
RECORDING_MAX_MINUTES = 180  # warsztaty run >2h; the cap-stop now publishes correctly, but don't truncate them
```

(If the current line carries a different trailing comment, replace the whole line with the above.)

- [ ] **Step 3: Compile-check + suite**

Run: `python3 -m py_compile cogs/voicerecord.py config.py && python3 -m unittest discover tests`
Expected: silent compile; suite green except pre-existing `test_activity_embed`.

- [ ] **Step 4: Update CLAUDE.md**

Three edits:

1. Config table row `| RECORDING_MAX_MINUTES | 120 | Safety cap; auto-stops a forgotten recording |` → `| RECORDING_MAX_MINUTES | 180 | Safety cap; auto-stops a forgotten recording (cap-stop publishes normally) |`
2. In **The Daily Coaching recording pipeline** section, after the sentence about `RECORDING_MAX_MINUTES` being a hard safety stop, append: `On startup the cog also recovers orphaned WAVs (recordings without a transcript, e.g. after a crash mid-recording) — transcode → transcribe → save → upload, best-effort.`
3. Changelog — add at the top of the `**2026-08**` section:

```markdown
- **Nagrania ≥cap już nie giną + odzyskiwanie sierot** — `_safety_stop` po
  osiągnięciu limitu anulował własny task w `_teardown` (self-cancel), przez co
  transkod/Whisper/transkrypt/Drive/notify nigdy nie ruszały: przepadły
  warsztaty 14/21/28.07, a zawieszony stan blokował auto-record (stąd brak
  daily 28–29.07). Fix: `taskutil.cancel_unless_current` + czyszczenie handle
  przed pipeline'em; recovery przy starcie dokańcza pipeline dla WAV-ów bez
  transkryptu (`transcripts.find_orphans` + `parsers.parse_recording_filename`,
  unit-testy); `_finish_and_publish` w twardym wrapperze (log + alert na kanał
  mod-only zamiast cichej śmierci); `RECORDING_MAX_MINUTES` 120→180;
  `list_transcripts` sortuje po pełnym datetime (remis tego samego dnia był
  losowy).
```

- [ ] **Step 5: Commit**

```bash
git add cogs/voicerecord.py config.py CLAUDE.md
git commit -m "feat(voicerecord): loud publish-pipeline failures, cap 180 min

Wrap the pipeline so a failure/cancel logs an exception and alerts the
mod channel instead of dying silently; raise the safety cap to 180 min
so warsztaty aren't truncated. Docs: config table, pipeline notes,
changelog."
```

---

### Task 7: deploy to mikrus + verify recovery (MAIN THREAD — not a subagent)

Prod access (`ssh mikrus`) and service restarts stay in the main session.

- [ ] **Step 1: Push**

```bash
git push
```

- [ ] **Step 2: Deploy**

```bash
ssh mikrus "cd /home/ludwikc/Momentum && sudo -u ludwikc git pull && venv/bin/python -m py_compile main.py config.py parsers.py transcripts.py taskutil.py cogs/voicerecord.py && venv/bin/python -m unittest discover tests && systemctl restart momentum-bot && systemctl is-active momentum-bot"
```

Expected: `Ran … tests … OK` (venv has discord — the whole suite passes there), then `active`.

- [ ] **Step 3: Watch the recovery**

```bash
ssh mikrus "journalctl -u momentum-bot --since '2 minutes ago' | grep -a 'voicerecord\|Recovering\|Orphaned' | head"
```

Expected: `Orphaned recordings to recover: ['Lifehackerzy_2026-07-23-12-34-46_…', 'Lifehackerzy_2026-07-28-06-30-40_…']` then per-file progress. Whisper on ~2h audio takes minutes — poll `bot.log`:

```bash
ssh mikrus "grep -a 'Transcript saved\|Recovery\|Odzyskane' /home/ludwikc/Momentum/bot.log | tail"
```

- [ ] **Step 4: Verify transcripts exist**

```bash
ssh mikrus "ls /home/ludwikc/Momentum/transcripts/ | grep -a '497188\|961c1e'"
```

Expected: `2026-07-23_12-34_1234-daily-coaching_497188.md` and `2026-07-28_06-30_warsztaty-lifehackerow_961c1e.md`.

- [ ] **Step 5: VPS cleanup (stale token + junk files)**

`main.py` reads the token exclusively from `private.py`; the `DISCORD_TOKEN` line in `.env` is the SIADLAXITY token (wrong bot) left over from before the split — it misleads debugging. Remove it and the June junk files:

```bash
ssh mikrus "cd /home/ludwikc/Momentum && sed -i '/^DISCORD_TOKEN=/d' .env && rm -f recordings/recording_2026-06-22_21-50-06.wav recordings/recording_2026-06-22_21-09-55.mp3 && grep -c DISCORD_TOKEN .env; ls recordings/"
```

Expected: `0` from grep; `recordings/` empty (or only in-flight files).

- [ ] **Step 6: Functional check**

On Discord, ask (as owner): `Momentum, o czym były warsztaty 28 lipca?` — expect an answer grounded in the recovered transcript (log shows `lista_spotkan` + `czytaj_spotkanie`).

---

## Self-Review (done at plan time)

- **Spec coverage:** fix self-cancel ✔ (T1), data recovery ✔ (T5+T7), startup recovery ✔ (T5), cap policy ✔ (T6), observability ✔ (T6), sort fix ✔ (T3), stale .env token + junk ✔ (T7).
- **Placeholders:** none — every step carries exact code/commands.
- **Type consistency:** `parse_recording_filename` returns `Optional[tuple[datetime, str, str]]`, consumed as `(started, slug, rec_id)` in T4/T5; `find_orphans(list[str], list[str]) -> list[str]` consumed in T5; `_publish_pipeline` keeps `_finish_and_publish`'s exact signature; `cancel_unless_current(Task | None)` matches `_teardown` usage.
