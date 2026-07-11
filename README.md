# Momentum Discord Bot

The community bot for the **siadlak.VIP / Lifehackerzy** Discord — it runs the daily
coaching ritual, tracks habits and streaks, and turns the daily call into a recorded,
transcribed, AI-summarised artifact.

Built on `discord.py`, backed by Supabase, with Google Drive + OpenAI for recordings.
Single-server, single-purpose, personal project — no setup docs here on purpose.

---

## Features

### 🎙️ Daily Coaching call (the 12:34 ritual)
- **Daily invite** — posts an `@here` invite to the Daily Coaching voice channel at 12:34 (Warsaw).
- **Session reminders** — scheduled nudges through the call (12:34 start, 12:45 / 12:54 mid-call,
  12:59 wrap-up). The mid-call reminders show a **live Discord countdown to 13:00** that ticks
  down and localises per viewer.
- **Auto-recording** — starts recording when ≥2 people are in the channel and stops when it
  empties; manual `/nagraj` + `/stop_nagrywania` for mods. Includes a custom **DAVE (E2EE)
  decryption patch** so Discord's mandatory end-to-end encryption doesn't produce silent files.
- **Recording pipeline** — mixes to MP3, uploads to a **Google Drive Shared Drive** (private,
  mod-only link), then **transcribes (Whisper)** and posts an **AI summary (gpt-4o-mini, Polish
  coaching-notes format)** to the channel, with the full transcript stored next to the audio.
- **Thank-you + summary gating** — both the "dzięki za dzisiejsze rozkminki!" greeting and the
  summary are posted only for real group calls (≥2 participants).
- **Speaking queue** — `/kolejka` lets people line up to speak, with automatic mute/unmute
  handling as the queue advances.

### 🔥 Habits & streaks
- **Morning wake-ups** — `/gm` and an early-window listener (04:00–06:55) track and reward early rises.
- **Activity logging** — `/done` (and legacy text-prefix commands) log trening 💪, medytacja 🧘,
  sukces 💎, dziennik 📝, with monthly + consecutive-day + lifetime streak displays.
- **Tuesday meditation streak** — credits everyone in the meditation voice channel during the
  Tuesday 06:00 window.
- **Deep Work sessions** — `session_tracker` banks connected time (periodically, so restarts and
  long sessions don't lose progress) and posts progress.
- **Photo proof** — photo-reply listener with an author-locked "trening" confirmation button.
- **Leaderboards** — `/leaderboard` ranks top performers per activity.

### 🧰 Productivity suite (StudyLion port)
- **To-do list** — `/todo` with stable numbering, range operations (`1,3-5`, `all`), a toggle
  select menu, and coin rewards per completed task (capped per 24h).
- **Reminders** — `/przypomnij` (DM): relative (`za:3h`) or wall-clock (`o:16:00`, Warsaw),
  optional repeats that never burst after downtime; `/przypomnienia` to list/cancel.
- **Pomodoro** — `/pomodoro` runs a shared focus/break timer per voice channel with live Discord
  countdowns; survives bot restarts mid-cycle, auto-restarts when someone rejoins.
- **Voice-time tracking** — every voice channel counts toward daily/weekly/monthly/lifetime
  stats (`/statystyki`) and mints coins.
- **Coin economy** 🪙 — earned via voice time, tasks, `/done`, GM; `/portfel`, `/przelew`,
  a colour-role **shop** (`/sklep`), and a **rank ladder** for voice hours (`/rangi`).

### 💬 Community & engagement
- **Q&A** — `/pytanie` answers frequently-asked questions.
- **Anonymous messages** — `/anonim` and `/sekret` relay anonymous posts to dedicated channels.
- **Auto role assignment** — tracks which invite each new member used and assigns roles accordingly.

### 🛠️ Under the hood
- Supabase backend (migrated off MongoDB).
- Per-guild slash-command sync (instant) instead of global.
- Graceful degradation: recording works even if Google Drive / OpenAI are unconfigured, falling
  back to local storage and skipping the summary.

---

## Roadmap / ideas

Loose, for-fun list — not commitments.

- [ ] **Enable summaries in production** — currently blocked on OpenAI billing/quota; the pipeline
      is built and ready.
- [ ] **Auto-publish summaries to the Platform** — the reminder already promises "podsumować na
      Platformie"; close the loop automatically.
- [ ] **Searchable summary archive** — index past summaries (by date/topic) for quick lookup.
- [ ] **Speaking-time analytics** — per-participant talk time from the recording's per-user tracks.
- [ ] **Weekly digest** — roll up the week's calls, streaks, and leaderboard movers into one post.
- [ ] **Action-item extraction** — pull concrete follow-ups out of each call (was trimmed from the
      summary; could live as an opt-in personal DM instead).
- [ ] **Multi-channel auto-record** — watch more than one voice channel.
- [ ] **Streak recovery / freezes** — let people protect a streak on a missed day.
- [x] **Personal stats dashboard** — shipped as `/statystyki`.
- [ ] **StudyLion port, wave 2** — private rented rooms, scheduled accountability sessions,
      rolemenus, message XP, weekly/monthly goals (blueprints in
      `docs/superpowers/specs/2026-07-11-studylion-port-design.md`).
