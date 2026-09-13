# Momentum Discord Bot

The community bot for the **siadlak.VIP / Lifehackerzy** Discord — it runs the daily
coaching ritual, tracks habits and streaks, turns the daily call into a recorded,
transcribed, AI-summarised artifact, and takes part in the conversation itself: in
text when called by name, and — since 09.2026 — out loud in the voice channel.

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
- **Speaker-labelled transcripts** — Discord tells the sink which member every audio frame came
  from, so turns are attributed **without acoustic ML**: a ground-truth speaking timeline is
  recorded alongside the audio and the Whisper words are matched to it by timestamp. The result
  is a markdown transcript (frontmatter + diarised body) kept byte-identical on disk and on Drive.
- **Transcript lookup** — `/admin transkrypt <data>` returns the transcript and audio links for a
  given meeting, so nobody has to dig through Drive by hand.
- **Nothing fails quietly** — a failed transcription is appended to the same mod-only message that
  carries the audio link, and an *exhausted OpenAI balance* (permanent, unlike a throttling 429)
  tags the owner. Exhausted credits once ate 9 days of summaries unnoticed, because the pipeline
  degraded politely; it can't any more.
- **Crash recovery** — a recording orphaned by a crash or restart (audio with no transcript) is
  finished on the next startup: transcode → transcribe → save → upload.
- **Thank-you + summary gating** — both the "dzięki za dzisiejsze rozkminki!" greeting and the
  summary are posted only for real group calls (≥2 participants).
- **Speaking queue** — `/kolejka` lets people line up to speak, with automatic mute/unmute
  handling as the queue advances.

### 🤖 Momentum as a participant
- **Summoning** — say "Momentum" (or @-mention it) in any channel and it replies in character,
  with the recent conversation as context. It can look up **past meeting transcripts** to answer
  things like "what did Jakub say at yesterday's call", and consult a knowledge base.
- **Coaching mode** — an explicit coaching request switches it into a grounded coaching reply;
  it can also *offer* coaching when a question has real potential, on a cooldown so it never nags.
- **Vision** — images attached to a summon are actually sent to the model (admin-only).
- **Live voice replies** 🔊 — during a recorded call, an utterance starting with "Momentum" is
  transcribed, answered by the same brain, and **spoken back into the channel** (~11 s end to end).
  It yields the floor when a person talks over it, and its own voice is mixed into the
  recording, so it appears in the transcript and the summary like any other speaker.
  Admin-gated for now; non-authorised speech is never even sent to Whisper.
- **`/admin-task`** — owner-only executive mode: Momentum reads a link or a channel, drafts a
  message in Ludwik's voice, and shows it as an ephemeral preview. **Nothing reaches the server
  without a [Wyślij] click.**
- **Weekly digest** — every Friday the owner gets a DM with a ready-to-paste announcement
  summarising the week's Daily Coaching calls, written from the transcripts.

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
- **Profile cards** — `/profil` with custom self-description tags (edited in a modal),
  rank progress, wallet and voice-time highlights.

### 💬 Community & engagement
- **Q&A** — `/pytanie` answers frequently-asked questions.
- **Anonymous messages** — `/anonim` and `/sekret` relay anonymous posts to dedicated channels.
- **Auto role assignment** — tracks which invite each new member used and assigns roles accordingly.
- **Social link previews** — a message that is *only* an Instagram/TikTok link gets a reply through
  a proxy domain so the preview actually plays, and the dead original embed is suppressed.

### 🛠️ Under the hood
- Supabase backend (migrated off MongoDB).
- Per-guild slash-command sync (instant) instead of global.
- Bot-identity guard: refuses to start under any token that isn't Momentum's.
- Custom mixing audio sink — every speaker summed onto one timeline positioned by **RTP
  timestamp** rather than arrival time, so network jitter can't crackle or drift the recording.
- Pure-logic modules with stdlib unit tests (`python3 -m unittest discover tests`) — parsers,
  pomodoro arithmetic, wake-word and speech cleanup, transcript rendering.
- Graceful degradation: recording works even if Google Drive / OpenAI are unconfigured, falling
  back to local storage and skipping the summary.

---

## Roadmap / ideas

Loose, for-fun list — not commitments.

- [x] **Enable summaries in production** — live since 09.2026 (credits topped up, and a failure
      now shouts instead of degrading quietly).
- [ ] **Auto-publish summaries to the Platform** — the reminder already promises "podsumować na
      Platformie"; close the loop automatically.
- [ ] **Searchable summary archive** — index past summaries (by date/topic) for quick lookup.
      Partly covered by `/admin transkrypt` and the model's transcript tools.
- [ ] **Speaking-time analytics** — per-participant talk time. The diarisation timeline already
      records exactly this; nothing reports on it yet.
- [x] **Weekly digest** — shipped as the Friday DM; streaks and leaderboard movers still to add.
- [ ] **Voice bookmarks** — say "Momentum" during a call to mark the moment, then ask for the
      marked fragments later (designed, not built:
      `docs/superpowers/specs/2026-08-18-voice-bookmarks-design.md`).
- [ ] **Unprompted voice interjections** — let Momentum decide *itself* when to speak up in a call.
      Deliberately deferred: the code is small, but tuning "when is it OK to interrupt people"
      is the whole job.
- [ ] **Action-item extraction** — pull concrete follow-ups out of each call (was trimmed from the
      summary; could live as an opt-in personal DM instead).
- [ ] **Multi-channel auto-record** — watch more than one voice channel.
- [ ] **Streak recovery / freezes** — let people protect a streak on a missed day.
- [x] **Personal stats dashboard** — shipped as `/statystyki`.
- [ ] **StudyLion port, wave 2** — private rented rooms, scheduled accountability sessions,
      rolemenus, message XP, weekly/monthly goals (blueprints in
      `docs/superpowers/specs/2026-07-11-studylion-port-design.md`).
