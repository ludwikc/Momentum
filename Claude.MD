# Momentum Discord Bot — Developer Reference

Polish-language Discord bot for the **siadlak.VIP / Lifehackerzy** community. Runs the daily
12:34 coaching ritual (invite → reminders → auto-recording → transcript → AI summary), tracks
habits/streaks, and handles community plumbing (anonymous posts, Q&A, invite-based roles).

Single-server, single-maintainer project. No setup walkthrough here on purpose — this is a
reference for working on the running bot.

- **Framework:** discord.py 2.7 (+ `discord-ext-voice-recv` for recording)
- **Data store:** Supabase (PostgreSQL via RPC) — *migrated off MongoDB*
- **External services:** Google Drive (recording storage), OpenAI (Whisper + gpt-4o-mini)
- **Timezone:** everything time-based uses `Europe/Warsaw`
- **Language:** Polish (user-facing); English (code/internal)

---

## Table of Contents
- [Architecture](#architecture)
- [Running & restarting](#running--restarting)
- [Project structure](#project-structure)
- [Configuration](#configuration)
- [Environment variables](#environment-variables)
- [Helper modules](#helper-modules)
- [Database (Supabase)](#database-supabase)
- [Cogs](#cogs)
- [The Daily Coaching recording pipeline](#the-daily-coaching-recording-pipeline)
- [Commands / listeners / tasks reference](#commands--listeners--tasks-reference)
- [Known issues & cleanup](#known-issues--cleanup)
- [Roadmap](#roadmap)
- [Changelog](#changelog)

---

## Architecture

Cog-based: `main.py` loads each feature as an extension from the `EXTENSIONS` list, configures
intents + logging, and syncs slash commands **per-guild** (they appear instantly, vs ~1h for
global) then clears the global set so commands don't show up twice.

```
main.py (core)
  ├─ load_dotenv() + logging → bot.log + stderr (logger "momentum_bot")
  ├─ intents: message_content, members, voice_states, guilds
  ├─ load EXTENSIONS (17 cogs)
  ├─ on_ready: per-guild command sync, then clear global
  └─ graceful shutdown on SIGINT/SIGTERM (posts offline notice)

db.py  → Supabase client singleton + thin RPC wrappers (no direct SQL)
config.py → all channel IDs, time windows, recording/OpenAI settings
gdrive.py / transcribe.py / dave_patch.py → recording-pipeline helpers
```

Key facts:
- **Owner ID:** `404038151565213696` · **Status/notify channel:** `1015575570760880168`
- **Recorder account mentioned in the 12:34 reminder:** `272937604339466240`
- All scheduled logic polls once per minute against Warsaw-local time.

---

## Running & restarting

The bot runs as a backgrounded `venv/bin/python main.py` (daemon style per `run_bot.sh --daemon`),
PID in `bot.pid`, stdout/stderr appended to `bot.log`. It **must** use the project venv
(`/root/Momentum/venv`) — system `python3` lacks `discord.ext.voice_recv` and `davey`.

Restart after a code change:
```bash
kill $(cat bot.pid)                         # wait for exit; SIGKILL only if it lingers
nohup venv/bin/python main.py >> bot.log 2>&1 &
echo $! > bot.pid
# then confirm in bot.log: "cog is ready", "Synced N commands", no traceback
```
Byte-compile changed files first: `venv/bin/python -m py_compile <files>`. Doc-only changes need
no restart.

---

## Project structure

```
/root/Momentum/
├── main.py                  # entry point: intents, logging, per-guild sync, EXTENSIONS
├── config.py                # all constants (channels, windows, recording/OpenAI)
├── db.py                    # Supabase client + RPC wrappers
├── gdrive.py                # Google Drive Shared-Drive upload helper
├── transcribe.py            # OpenAI Whisper transcription + gpt-4o-mini summary
├── dave_patch.py            # runtime DAVE (E2EE) decryption patch for voice_recv
├── activity_embed.py        # unified progress-card builder (activities + Daily Coaching + Deep Work) + Polish duration/plural helpers
├── random_msg.py            # inspirational quote list (used by /gm)
├── private.py               # DISCORD_TOKEN (gitignored)
├── gdrive_service_account.json  # GCP service-account key (gitignored)
├── .env                     # secrets/config (gitignored)
├── data/now_recording.mp3   # "now recording" intro sound
├── recordings/              # transient WAV/MP3 during a recording (gitignored)
├── run_bot.sh               # launcher (foreground / --daemon)
└── cogs/                    # 17 feature extensions (see below)
```

Stray/unused (see [Known issues](#known-issues--cleanup)): `Momentum/` (nested stale copy),
`linkdb.py`, `emoji.py`, `images.py`.

---

## Configuration

All in `config.py`:

| Constant | Value | Meaning |
|---|---|---|
| `DAILY_CALL_CHANNEL_ID` | `1120658406160732160` | Daily coaching voice channel (also the auto-record + queue + session target) |
| `PROGRESS_CHANNEL_ID` | `1225131519404675124` | Where activity/streak embeds are posted |
| `SEKRET_CHANNEL_ID` | `1196136652737892463` | Anonymous secrets channel |
| `ACTIVITIES` | `{trening 💪, medytacja 🧘, sukces 💎, dziennik 📝}` | Activity types → emoji |
| `MORNING_GREETING_START_HOUR` / `_END_HOUR` / `_END_MINUTE` | `4` / `6` / `55` | GM early-bird window (04:00–06:55) |
| `RECORDING_NOTIFY_CHANNEL_ID` | `1015575570760880168` | Mod-only channel for the Drive link |
| `RECORDING_MAX_MINUTES` | `120` | Safety cap; auto-stops a forgotten recording |
| `AUTO_RECORD_ENABLED` | `True` | Master switch for presence-based auto-record |
| `AUTO_RECORD_CHANNEL_IDS` | `[1120658406160732160]` | Voice channels watched for auto-record |
| `AUTO_RECORD_MIN_MEMBERS` | `2` | Non-bot members needed to start/keep auto-record |
| `START_SOUND_CHANNEL_IDS` | `[1120658406160732160]` | Channels where the intro sound plays on start |
| `DAILY_INVITE_CHANNEL_ID` | `1128649406640558110` | Where the daily @here invite is posted |
| `DAILY_INVITE_VOICE_CHANNEL_ID` | `1120658406160732160` | Voice channel linked in the invite |
| `DAILY_INVITE_TIME` | `"12:34"` | Warsaw time for the invite |
| `RECORDING_THANKYOU_VOICE_CHANNEL_IDS` | `[1120658406160732160]` | Recorded channels that trigger a thank-you |
| `RECORDING_THANKYOU_CHANNEL_ID` | `1128649406640558110` | Where the participant thank-you is posted |
| `RECORDING_MIN_PARTICIPANTS` | `2` | Min distinct participants to post thank-you **and** summary |
| `RECORDING_SUMMARY_CHANNEL_ID` | `1128649406640558110` | Where the AI summary embed is posted |
| `OPENAI_TRANSCRIBE_MODEL` | `"whisper-1"` | Transcription model |
| `OPENAI_SUMMARY_MODEL` | `"gpt-4o-mini"` | Summary model |

A few channel IDs are still hardcoded inside cogs (not in config): GM channel
`1021389566445375558` (gmlistener/gm), meditation voice `988452597549641758`
(meditation_voice), deep-work voice `1023996094524424313` (queue_cog/session_tracker),
photo thread `1245416699453509682` (photo_reply), and the invite→role map in auto_assign_role.

---

## Environment variables

Loaded from `.env` via `load_dotenv()` (token also read from `private.py`).

| Var | Used by | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | private.py / main.py | Bot token |
| `SUPABASE_URL`, `SUPABASE_KEY` | db.py | Supabase project + key |
| `GDRIVE_SA_JSON` | gdrive.py | Path to the service-account JSON key |
| `GDRIVE_FOLDER_ID` | gdrive.py | Destination folder in the Shared Drive |
| `OPENAI_API_KEY` | transcribe.py | Enables transcription + summary |
| `DEBUG_ASYNCIO` | main.py | Optional asyncio debug mode |

All of `GDRIVE_*` / `OPENAI_API_KEY` are optional — the recording pipeline degrades gracefully
(keeps audio local / skips the summary) when they're unset.

---

## Helper modules

**`gdrive.py`** — uploads a file to a Google Drive **Shared Drive** folder (service accounts can't
write to a personal My Drive). `is_configured()` is true only when both `GDRIVE_SA_JSON` (existing
file) and `GDRIVE_FOLDER_ID` are set. `upload_file()` is blocking → call via `asyncio.to_thread`;
returns `{id, webViewLink}`. Scope: `drive.file`, `supportsAllDrives=True`.

**`transcribe.py`** — `transcribe(path)` down-mixes the MP3 to 16 kHz mono Opus (`.ogg`, ~16 kbps)
via ffmpeg to stay under OpenAI's 25 MB upload cap, then calls Whisper with a Polish language hint.
`summarize(transcript, channel_name)` calls gpt-4o-mini with a Polish coaching-notes system prompt
and returns Markdown with **📌 Główne tematy** and **💡 Kluczowe wnioski** sections. Both blocking;
`is_configured()` keys off `OPENAI_API_KEY`.

**`dave_patch.py`** — monkey-patches `voice_recv.opus.PacketDecoder._decode_packet` to DAVE-decrypt
each transport-decrypted payload (`dave_session.decrypt(user_id, MediaType.audio, payload)`) before
Opus decoding. Discord now mandates DAVE/MLS E2EE on voice; without this every recording is silent
("corrupted stream"). Also makes decode failures non-fatal (emit a silence frame instead of killing
the packet-router thread). `apply()` is idempotent and called at import of `voicerecord.py`.

---

## Database (Supabase)

`db.py` exposes a singleton client (`SUPABASE_URL` + `SUPABASE_KEY`) and thin wrappers over
PostgreSQL RPC functions — no client-side SQL/query building. RPCs:

| RPC | Params | Returns / purpose |
|---|---|---|
| `upsert_activity` | `p_discord_id`, `p_activity`, `p_xp_amount=10` | Log an activity; auto monthly reset; returns streaks |
| `get_user_activity_stats` | `p_discord_id` | Everything the unified progress card shows: monthly streaks + lifetime activity totals + `total_daily_coaching`, `total_deep_work`, `deep_work_seconds` (or None). Extended by `scripts/unified_progress_stats.sql` |
| `get_activity_leaderboard` | `p_activity`, `p_limit=10` | Ranked `{rank, discord_id, streak_count, user_id}`; also accepts `daily_coaching`/`deep_work` (this month's join count) after `scripts/unified_leaderboard.sql` |
| `log_capped_join` | `p_discord_id`, `p_activity`, `p_max_per_day` | Daily-capped join (daily_coaching/deep_work); `{logged, monthly_count, total_count}` |
| `add_deep_work_time` | `p_discord_id`, `p_seconds` | Bank deep-work seconds; `{total_seconds}` |
| `check_morning_checkin` | `p_discord_id` | GM check-in; `{success, is_early_bird, current_momentum, total_checkins, message}` |
| `get_wakeup_leaderboard` | `p_type` (`total`/`momentum`/`early_bird`), `p_limit=10` | Wake-up ranking |
| `link_discord_to_portal_user` | `p_discord_id`, `p_user_id` | Link Discord ↔ Platform account |

Streak/cap/day logic lives server-side in the RPCs and is Warsaw-day aware.

---

## Cogs

Loaded in this order (`main.py` `EXTENSIONS`):

| # | Cog | What it does | Commands / triggers |
|---|---|---|---|
| 1 | `test_cog` | Debug only | `!hello` |
| 2 | `gmlistener` | Early-bird GM tracking: on messages matching `\bgm\b`/"dzień dobry" in the GM channel, 04:00–06:55, calls `check_morning_checkin`; emoji-only users get an emoji reply, others a greeting + momentum/streak | `on_message` (GM channel `1021389566445375558`) |
| 3 | `gm` | Slash version of the GM check-in; public "Momentum: N" + ephemeral quote | `/gm` |
| 4 | `dailyreminder` | Four timed session messages; 12:45 & 12:54 show a **live Discord countdown to 13:00** (`<t:…:R>`) | tasks.loop 1m → 12:34/12:45/12:54/12:59 |
| 5 | `auto_assign_role` | Caches invites, diffs use-counts on join, assigns a role per the hardcoded invite→role map | `on_member_join`, `on_member_remove`, tasks.loop 1m |
| 6 | `prefixdone` | Nudges legacy `!`-commands to `/done` | `!trening`/`!medytacja`/`!sukces`(`!sumit`,`!mit`)/`!dziennik`/`!done` |
| 7 | `done` | Logs an activity (`upsert_activity`) and posts a streak embed (monthly + consecutive-day + lifetime) | `/done <activity>` |
| 8 | `leaderboard` | Top-10 monthly ranking embed for any progress-card category (4 activities + Daily Coaching + Deep Work) | `/leaderboard <activity>` |
| 9 | `sekret` | Posts an anonymous secret (spoiler-wrapped, role-pinged) in the secrets channel | `/sekret <message>` (1–1900 chars) |
| 10 | `anonim` | Posts an anonymous spoiler message inline in the same channel | `/anonim <message>` |
| 11 | `qacog` | FAQ lookup against ~5 hardcoded Q&A pairs (exact + partial match) | `/pytanie <question>` |
| 12 | `queue_cog` | Speaking queue with arrow at the current speaker; advances on mute, re-shows on unmute; greets joiners (daily + deep-work, deep-work greeting once/day) | `/kolejka`; `on_voice_state_update` (`1120658406160732160`, deep-work `1023996094524424313`) |
| 13 | `photo_reply` | On a photo in the watched thread, offers an author-locked "trening" button → logs trening + posts embed | `on_message` (thread `1245416699453509682`) |
| 14 | `meditation_voice` | Tuesday 06:00–06:59 meditation-voice attendance; ≥10 min credits "medytacja"; welcome DM on join | `on_voice_state_update` (`988452597549641758`), tasks.loop 1m straggler sweep |
| 15 | `session_tracker` | Daily-coaching joins (cap 1/day) and deep-work joins (cap 3/day) via `log_capped_join`; posts the shared unified progress card (`build_progress_embed`); banks deep-work time on leave and periodically | `on_voice_state_update`, tasks.loop 10m flush |
| 16 | `voicerecord` | The recording pipeline (see below) | `/nagraj`, `/stop_nagrywania` (mod-only), auto-record |
| 17 | `daily_invite` | Posts the 12:34 `@here` invite to the coaching channel (once/day guard) | tasks.loop 1m |

---

## The Daily Coaching recording pipeline

The flagship feature, spread across `voicerecord.py` + the three helper modules.

**Start** — manual `/nagraj` (requires `manage_guild`; user must be in a voice channel; shows an
ephemeral panel with a Stop button), or **auto-record**: when a watched channel
(`AUTO_RECORD_CHANNEL_IDS`) reaches `AUTO_RECORD_MIN_MEMBERS` non-bot members it starts; when it
drops below, it stops. One recording at a time, serialized by an `asyncio.Lock`; a 60 s
`auto_sweep` backstops missed voice-state events. `dave_patch.apply()` runs at import so E2EE audio
decodes. Optional intro sound plays on `START_SOUND_CHANNEL_IDS`.

**Capture** — `voice_recv.VoiceRecvClient` with a `SilenceGeneratorSink(WaveSink)` keeps the
timeline intact during silence → WAV in `recordings/`, named
`Lifehackerzy_<ts>_<channel-slug>_<rec_id>.wav`. Participants are accumulated from voice-state
updates. `RECORDING_MAX_MINUTES` is a hard safety stop.

**On stop** (`_finish_and_publish`):
1. Teardown, transcode WAV → MP3 (ffmpeg libmp3lame `-qscale:a 4`), delete WAV.
2. If `transcribe.is_configured()`: transcribe (Whisper) + summarize (gpt-4o-mini), off-thread.
3. If `gdrive.is_configured()`: upload the MP3, plus the transcript as a `.txt` alongside it;
   delete local copies. Otherwise keep the MP3 locally.
4. Post the Drive link (or local path) to the **notify channel** (`RECORDING_NOTIFY_CHANNEL_ID`,
   mod-only) — this always happens.
5. **Only if `≥ RECORDING_MIN_PARTICIPANTS` (2)**: post the thank-you ("…dzięki za dzisiejsze
   rozkminki!") tagging participants, and the **summary embed** to `RECORDING_SUMMARY_CHANNEL_ID`.
   The summary header is the recorded channel as a clickable mention + the date
   (`<#…> z dn. <t:…:D>`); the Drive link is deliberately **not** in the public summary.

Everything in steps 2–3 is best-effort and wrapped — a transcription/Drive failure never blocks
publishing or the bot.

---

## Commands / listeners / tasks reference

**Slash:** `/gm`, `/done <activity>`, `/leaderboard <activity>`, `/sekret <msg>`, `/anonim <msg>`,
`/pytanie <q>`, `/kolejka`, `/nagraj`, `/stop_nagrywania` (last two mod-only).
**Prefix:** `!hello`; legacy `!trening`/`!medytacja`/`!sukces`/`!dziennik`/`!done` (redirect to `/done`).

**Listeners:** `on_message` (gmlistener, photo_reply), `on_member_join`/`on_member_remove`
(auto_assign_role), `on_voice_state_update` (queue_cog, meditation_voice, session_tracker,
voicerecord).

**Background tasks:** daily_invite 1m · dailyreminder 1m · auto_assign_role invite cache 1m ·
meditation_voice straggler sweep 1m · voicerecord auto_sweep 60s · session_tracker deep-work flush 10m.

---

## Known issues & cleanup

- **Stray `Momentum/` dir** — a nested 2024 copy of the project (its own `main.py`/`cogs/`), not
  loaded. Safe to delete.
- **Dead modules** — `linkdb.py` (old MongoDB string), `emoji.py`, `images.py` are imported
  nowhere. Safe to delete.
- **`validate_token()` in main.py** is imported but the call is commented out.
- **OpenAI summaries are blocked in production** by billing/quota on the OpenAI project
  (`429 insufficient_quota`) — code is ready; recording + Drive upload work regardless.
- **Hardcoded channel IDs** inside several cogs (GM, meditation, deep-work, photo thread, invite
  map) rather than centralized in `config.py` — fine for a single server.

---

## Roadmap

Loose, not commitments (mirrors README):

- [ ] **Enable summaries in production** — add OpenAI billing; pipeline already built.
- [ ] **Auto-publish summaries to the Platform** — the 12:34 message already promises it.
- [ ] **Searchable summary archive** — index past summaries by date/topic.
- [ ] **Speaking-time analytics** — per-participant talk time from per-user recording tracks.
- [ ] **Weekly digest** — roll up calls, streaks, leaderboard movers.
- [ ] **Action-item extraction** — opt-in per-person follow-ups (was trimmed from the summary).
- [ ] **Multi-channel auto-record**, **streak freezes**, **personal stats dashboard**.
- [ ] **Cleanup** — delete the stray `Momentum/` dir and the dead `linkdb.py`/`emoji.py`/`images.py`.

---

## Changelog

**2026-07**
- **Unified the leaderboard**: `/leaderboard` now covers all six progress-card categories —
  Daily Coaching and Deep Work rank by this month's joins (Warsaw month) via an extended
  `get_activity_leaderboard` (`scripts/unified_leaderboard.sql`, must be applied in
  Supabase or the two new options error out gracefully). Removed the unused
  `get_deep_work_seconds` wrapper from `db.py`. Spec:
  `docs/superpowers/specs/2026-07-11-unified-leaderboard-design.md`.
- **Unified the progress card**: every post to the progress channel (activities, Daily
  Coaching, Deep Work) now renders the same full per-user card via
  `activity_embed.build_progress_embed` — event-specific headline + all lifetime counters,
  incl. `🔢 Daily Coaching: N` and `⚓️ Deep Work: <czas> (<sesje>)`. Requires applying
  `scripts/unified_progress_stats.sql` (extends `get_user_activity_stats`); until then the
  two new rows are simply omitted. Spec:
  `docs/superpowers/specs/2026-07-03-unified-progress-card-design.md`.

**2026-06 (last ~6 months of work)**
- Migrated the entire data layer from **MongoDB → Supabase** (`db.py` RPCs).
- Added the **voice recording pipeline**: auto-record + `/nagraj`, DAVE/E2EE decryption patch,
  MP3 transcode, Google Drive upload, Whisper transcription, gpt-4o-mini Polish summaries.
- Added **session tracking** (daily-coaching + deep-work caps, deep-work time banking),
  **Tuesday meditation** voice streaks, **photo-proof** trening button.
- Added the **daily 12:34 invite**, reworked streak display (monthly + consecutive + lifetime),
  switched to **per-guild** command sync.
- Summary post refined: channel-mention + date header, dropped the tasks section, Drive link kept
  mod-only. Thank-you + summary now gated on ≥2 participants. Reminders use a live 13:00 countdown.

---

*Reference doc — kept current by Claude Code. Repo: ludwikc/Momentum · branch: main.*
