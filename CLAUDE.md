# Momentum Discord Bot — Developer Reference

Polish-language Discord bot for the **siadlak.VIP / Lifehackerzy** community. Runs the daily
12:34 coaching ritual (invite → reminders → auto-recording → transcript → AI summary), tracks
habits/streaks, ships a StudyLion-style productivity suite (todo, przypomnienia, pomodoro,
voice-time stats, coin economy + shop + rangi), and handles community plumbing (anonymous
posts, Q&A, invite-based roles).

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
  ├─ load EXTENSIONS (30 cogs)
  ├─ on_ready: per-guild command sync, then clear global
  └─ graceful shutdown on SIGINT/SIGTERM (posts offline notice)

db.py  → Supabase client singleton + thin RPC wrappers (no direct SQL)
config.py → all channel IDs, time windows, recording/OpenAI settings
gdrive.py / transcribe.py / dave_patch.py → recording-pipeline helpers
```

Key facts:
- **Owner ID:** `404038151565213696` · **Status/notify channel:** `1015575570760880168`
- **Bot identity (Discord app):** Momentum — `1468726880395067412` (`config.MOMENTUM_BOT_ID`).
  SIADLAXITY (`1363266006516105456`) is a *separate* app (the siadlak.VIP portal bot);
  `main.py` guards this at startup and refuses to run under any other token.
- **Recorder account mentioned in the 12:34 reminder:** `272937604339466240`
- All scheduled logic polls once per minute against Warsaw-local time.

---

## Running & restarting

Production runs on the mikrus VPS (`ssh mikrus`, login as root; host `ula285`) as the systemd
service **`momentum-bot.service`** — `User=ludwikc`, `WorkingDirectory=/home/ludwikc/Momentum`,
`ExecStart=/home/ludwikc/Momentum/venv/bin/python3 main.py`, `Restart=on-failure`. The repo is
owned by user `ludwikc`, so when logged in as root run git via `sudo -u ludwikc git …` (plain
`git` fails with "dubious ownership"). The bot **must** use the project venv
(`/home/ludwikc/Momentum/venv`) — system `python3` lacks `discord.ext.voice_recv` and `davey`.

Deploy after a code change:
```bash
cd /home/ludwikc/Momentum
sudo -u ludwikc git pull
venv/bin/python -m py_compile <changed files>
systemctl restart momentum-bot
systemctl is-active momentum-bot
journalctl -u momentum-bot --since "1 minute ago"   # expect "cog initialized", "Synced N commands", no traceback
```
Doc-only changes need no restart. (The old `run_bot.sh` / `bot.pid` / `nohup` flow is retired.)

---

## Project structure

```
/home/ludwikc/Momentum/
├── main.py                  # entry point: intents, logging, per-guild sync, EXTENSIONS
├── config.py                # all constants (channels, windows, recording/OpenAI)
├── db.py                    # Supabase client + RPC wrappers
├── gdrive.py                # Google Drive Shared-Drive upload helper
├── transcribe.py            # OpenAI Whisper transcription + gpt-4o-mini summary
├── dave_patch.py            # runtime DAVE (E2EE) decryption patch for voice_recv
├── activity_embed.py        # unified progress-card builder (activities + Daily Coaching + Deep Work + voice/tasks/coins) + Polish duration/plural helpers
├── parsers.py               # pure input parsers: durations ("3h", "1d 2h"), wall-clock ("16:00"), index ranges ("1,3-5") — unit-tested
├── pomodoro_math.py         # pure pomodoro stage arithmetic (last_started anchor) — unit-tested
├── tests/                   # stdlib-unittest tests for the pure helpers (python3 -m unittest discover tests)
├── random_msg.py            # inspirational quote list (used by /gm)
├── private.py               # DISCORD_TOKEN (gitignored)
├── gdrive_service_account.json  # GCP service-account key (gitignored)
├── .env                     # secrets/config (gitignored)
├── data/now_recording.mp3   # "now recording" intro sound
├── recordings/              # transient WAV/MP3 during a recording (gitignored)
├── run_bot.sh               # launcher (foreground / --daemon)
└── cogs/                    # 30 feature extensions (see below)
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
| `RECORDING_MAX_MINUTES` | `180` | Safety cap; auto-stops a forgotten recording (cap-stop publishes normally) |
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
| **StudyLion port** (spec: `docs/superpowers/specs/2026-07-11-studylion-port-design.md`) | | |
| `COINS_EMOJI` / `VOICE_COINS_PER_HOUR` / `VOICE_COIN_DAILY_CAP_HOURS` | 🪙 / `50` / `16` | Coin minting for voice time (pro-rated/s, Warsaw-day cap) |
| `TASK_REWARD_COINS` / `TASK_REWARD_LIMIT_24H` | `50` / `10` | Coins per completed todo task; max rewarded tasks per rolling 24h |
| `DONE_REWARD_COINS` / `GM_REWARD_COINS` | `10` / `10` | Coin bonus for `/done` (1×/activity/Warsaw-day) and the GM check-in |
| `TODO_MAX_OPEN` / `TODO_MAX_CONTENT` | `100` / `100` | Todo caps (open tasks / chars) |
| `PROFILE_MAX_TAGS` / `PROFILE_TAG_MAX_LEN` | `5` / `30` | /profil tag caps (StudyLion profile badges) |
| `REMINDER_MAX_PER_USER` / `REMINDER_MIN_REPEAT_SECONDS` / `REMINDER_MAX_CONTENT` | `25` / `600` / `2000` | Reminder caps |
| `POMODORO_DEFAULT_FOCUS_MIN` / `_BREAK_MIN` / `_MAX_STAGE_MIN` | `25` / `5` / `1440` | Pomodoro stage defaults/bounds |
| `UNTRACKED_VOICE_CHANNEL_IDS` / `VOICE_FLUSH_MINUTES` | `[]` / `5` | Voice-tracking exclusions + flush cadence |
| `VOICE_RANKS` / `RANKS_ANNOUNCE_CHANNEL_ID` | `[]` / progress channel | Rank ladder `(hours, role_id, reward)`; empty ⇒ ranks dormant |
| `WEEKLY_DIGEST_ENABLED` / `_WEEKDAY` / `_TIME` | `True` / `4` / `"14:00"` | Piątkowy digest DM (Warsaw) |
| `WEEKLY_DIGEST_LOOKBACK_DAYS` / `_CHANNEL_KEY` / `_PER_MEETING_CHARS` / `_MAX_TOKENS` | `6` / `"1234-daily-coaching"` / `8000` / `2000` | Zakres i budżety digestu |

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
| **StudyLion port** (`scripts/studylion_port.sql`) | | |
| `adjust_coins` / `award_activity_coins` / `get_coin_summary` / `transfer_coins` | discord_id, amount, reason… | Ledger-backed balance changes (floor 0), 1×/day /done bonus, wallet summary, atomic transfers |
| `todo_add/list/set_done/remove/edit` | discord_id, ids/content… | Todo CRUD; `todo_set_done` also mints task rewards (24h rolling cap) in-transaction |
| `reminder_add/list/cancel`, `reminders_due`, `reminder_ack` | … | Reminder CRUD + due-poll; ack advances repeats past missed occurrences / flags failures |
| `add_voice_time` / `get_voice_stats` | discord_id, channel, seconds, rate, cap | Warsaw-day voice aggregates + idempotent coin minting; today/week/month/total sums |
| `pomodoro_upsert/set_stopped/delete/list_all` | channel_id… | Persisted timers (last_started anchor ⇒ restart-resumable) |
| `record_rank_award` | discord_id, hours | One-time-per-threshold rank reward guard |
| `shop_list/add_item/remove_item/buy` | role_id, price… | Colour-role shop; `shop_buy` debits atomically |
| `profile_set_tags` (`scripts/profile_tags.sql`) | discord_id, tags[] | Replace /profil tags (≤5×30, validated server-side) |

`get_user_activity_stats` and `get_activity_leaderboard` are further extended by
`studylion_port.sql` (coins/voice/tasks/GM fields; `coins` + `voice` leaderboard categories) —
it supersedes `unified_progress_stats.sql`/`unified_leaderboard.sql`. `profile_tags.sql`
then redefines `get_user_activity_stats` once more (v4, adds `profile_tags`).

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
| 18 | `przywolanie` | Momentum replies when summoned by name/@mention (OpenAI, transcripts lookup, knowledge base, coaching CTA + limits) | `on_message` |
| 19 | `reboot` | Owner restarts the bot from Discord | `/momentum-reboot` |
| 20 | `economy` | Monety: wallet, transfers, owner grants (StudyLion port) | `/portfel`, `/przelew`, `/monety-admin` (owner) |
| 21 | `todo` | Per-user tasklist with coin rewards (50/task, ≤10/24h), range ops (`1,3-5`, `all`), toggle select menu | `/todo dodaj|lista|zrobione|cofnij|usun|wyczysc|edytuj` |
| 22 | `reminders` | DM reminders: relative (`za:3h`) or wall-clock (`o:16:00`), repeats ≥10 min with anti-burst advance, DM-ability probe at creation | `/przypomnij`, `/przypomnienia [usun:]`; tasks.loop 1m poller |
| 23 | `pomodoro` | Per-voice-channel focus/break timer (StudyLion `last_started` model): `<t:…:R>` countdowns in the VC chat, best-effort channel status, auto-stop when empty + auto-restart on join, resumes mid-cycle after bot restart | `/pomodoro start|stop|status`; `on_voice_state_update`; per-timer asyncio task |
| 24 | `voice_tracker` | Tracks time in ALL voice channels (minus `UNTRACKED_VOICE_CHANNEL_IDS`) into Warsaw-day aggregates; mints coins (50/h, ≤16h/day); dispatches `momentum_voice_flushed` | `on_voice_state_update`, tasks.loop 5m flush |
| 25 | `statystyki` | Personal stats embed: voice today/week/month/total, monety, zadania, activities, Daily Coaching, Deep Work, GM | `/statystyki [uzytkownik]` |
| 25a | `profil` | Profile card: custom tags (max 5×30, edit via author-locked modal button), rank + next-rank progress, monety, voice, GM momentum; needs `scripts/profile_tags.sql` | `/profil [uzytkownik]` |
| 26 | `ranks` | Voice-hour rank ladder (`VOICE_RANKS`): award-highest/remove-others roles, one-time coin rewards, public announcement; dormant when unconfigured | `/rangi`; listens to `momentum_voice_flushed` |
| 27 | `shop` | Colour-role shop (DB-driven items, single-slot swap without refund, atomic debit + refund on role failure) | `/sklep`; `/sklep-admin dodaj|usun|lista` (manage_guild) |
| 28 | `admin_task` | Owner-only tryb wykonawczy: agent (czytaj_link/czytaj_kanal/wyslij) czyta wskazane treści i szykuje szkice wiadomości głosem Momentum; okno bieżącego kanału doklejane zawsze (cichy summon "odpowiedz tutaj"); publikacja tylko po [Wyślij] w ephemeralnym podglądzie | `/admin-task <zadanie>` (owner) |
| 29 | `weekly_digest` | Piątek 14:00: DM do ownera z gotowym wzorem ogłoszenia-podsumowania tygodnia Daily Coaching (głos Ludwika wg rewriter-discord, tag @LIFEHACKERZY, transkrypty z 7 dni przez gpt) | `/podsumowanie-tygodnia` (owner); tasks.loop 1m |

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
updates. `RECORDING_MAX_MINUTES` is a hard safety stop. On startup the cog also recovers orphaned WAVs (recordings without a transcript, e.g. after a crash mid-recording) — transcode → transcribe → save → upload, best-effort.

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

**Slash:** `/gm`, `/done <activity>`, `/leaderboard <activity>` (8 categories), `/sekret <msg>`,
`/anonim <msg>`, `/pytanie <q>`, `/kolejka`, `/nagraj`, `/stop_nagrywania` (last two mod-only),
`/momentum-reboot` (owner) — plus the StudyLion port: `/portfel [user]`, `/przelew <komu> <ile>`,
`/monety-admin` (owner), `/todo <dodaj|lista|zrobione|cofnij|usun|wyczysc|edytuj>`,
`/przypomnij tekst: [za:|o:] [co:]`, `/przypomnienia [usun:]`,
`/pomodoro <start|stop|status>`, `/statystyki [user]`, `/profil [user]`, `/rangi`, `/sklep`,
`/sklep-admin <dodaj|usun|lista>` (manage_guild), `/admin-task <zadanie>` (owner),
`/podsumowanie-tygodnia` (owner).
**Prefix:** `!hello`; legacy `!trening`/`!medytacja`/`!sukces`/`!dziennik`/`!done` (redirect to `/done`).

**Listeners:** `on_message` (gmlistener, photo_reply, przywolanie), `on_member_join`/`on_member_remove`
(auto_assign_role), `on_voice_state_update` (queue_cog, meditation_voice, session_tracker,
voicerecord, voice_tracker, pomodoro), custom `momentum_voice_flushed` (ranks ← voice_tracker).

**Background tasks:** daily_invite 1m · dailyreminder 1m · auto_assign_role invite cache 1m ·
meditation_voice straggler sweep 1m · voicerecord auto_sweep 60s · session_tracker deep-work flush 10m ·
reminders due-poll 1m · voice_tracker flush 5m · pomodoro: one asyncio task per running timer ·
weekly_digest 1m.

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
- **Superseded SQL scripts** — `scripts/unified_progress_stats.sql` and
  `scripts/unified_leaderboard.sql` are fully contained in (and superseded by)
  `scripts/studylion_port.sql`; keep them only as history.

---

## Roadmap

Loose, not commitments (mirrors README):

- [ ] **Enable summaries in production** — add OpenAI billing; pipeline already built.
- [ ] **Auto-publish summaries to the Platform** — the 12:34 message already promises it.
- [ ] **Searchable summary archive** — index past summaries by date/topic.
- [ ] **Speaking-time analytics** — per-participant talk time from per-user recording tracks.
- [x] **Weekly digest** — piątkowy DM z podsumowaniem spotkań (cogs/weekly_digest.py); streaks/leaderboard movers wciąż do zrobienia.
- [ ] **Action-item extraction** — opt-in per-person follow-ups (was trimmed from the summary).
- [ ] **Multi-channel auto-record**, **streak freezes** (~~personal stats dashboard~~ → `/statystyki`).
- [ ] **StudyLion port, wave 2** — private rented rooms, scheduled accountability sessions,
  rolemenus, text/message XP, weekly-monthly goals, seasons (blueprints in the port spec).
- [ ] **Cleanup** — delete the stray `Momentum/` dir and the dead `linkdb.py`/`emoji.py`/`images.py`.

---

## Changelog

**2026-08**
- **Piątkowy digest Daily Coaching** — nowy cog `weekly_digest`: w każdy piątek
  o 14:00 (Warsaw) owner dostaje DM z gotowym do wklejenia wzorem ogłoszenia
  na #ogłoszenia (tag @LIFEHACKERZY, głos Ludwika wg skilla rewriter-discord —
  reguły stylu wbudowane w `digest.DIGEST_SYSTEM_PROMPT`), złożonym przez
  gpt z transkryptów 12:34 z ostatnich 7 dni (`digest.py` — czyste helpery
  z testami; ścieżki awaryjne zawsze wysyłają DM z diagnozą). Test na żądanie:
  `/podsumowanie-tygodnia` (owner-only). Config: `WEEKLY_DIGEST_*`.

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

- **`/admin-task` — owner-only tryb wykonawczy** (spec:
  `docs/superpowers/specs/2026-08-02-admin-task-design.md`): Ludwik zleca
  Momentum realne zadania ("zobacz <link> i odpowiedz", "napisz o X na
  <#kanał>", "odpowiedz tutaj" = cichy summon — okno bieżącego kanału
  doklejane do każdego zadania). Agent z narzędziami `czytaj_link` /
  `czytaj_kanal` / `wyslij` (nowe: `parse_message_link` w `parsers.py`,
  `format_channel_window` w `summon.py`, `_chat(tools=)` w przywołaniach);
  tryb ignoruje person-owe odmowy, ale NIC nie wychodzi na serwer bez
  kliknięcia [Wyślij] w ephemeralnym podglądzie (timeout 10 min, wysyłka
  bez @everyone/ról, `repair_mentions` + split na długich treściach).
  Config: `ADMIN_TASK_*` w `config.py`.

**2026-07**
- **Coaching: krótkie strzały + autonomia rozmówcy** (feedback z porannej rozmowy
  na Deep Work; spec: `docs/superpowers/specs/2026-07-31-coaching-brevity-autonomy-design.md`):
  odpowiedzi coachingowe max 4 zdania + jeden ruch (twardy limit w promptcie;
  cap 1500 tokenów podbijają już tylko narzędzia transkrypcji, nie
  `szukaj_w_bazie`); nowa sekcja SYSTEM_PROMPT „AUTONOMIA ROZMÓWCY I KONIEC
  ROZMOWY" (challenge raz, potem wspieraj plan usera; „znikam/idę działać" =
  jedno zdanie pożegnania, zero pytań); oferta coachingu wygasa cicho (koniec
  „Nie odpowiadasz…" + dumpa odpowiedzi) i ma 30-min cooldown per (kanał, user)
  (`MOMENTUM_COACHING_OFFER_COOLDOWN_S`, `offer_allowed` w `summon.py`).
- **`/profil` — student-profile-card port** (follow-up gap-fill from StudyLion's README:
  `!stats`/`!setprofile`): custom self-description tags (max 5×30, `;`-separated, edited via an
  author-locked modal button — StudyLion's "Edit Profile Badges" flow), plus rank + next-rank
  progress, monety, voice time and GM momentum on one card. New `scripts/profile_tags.sql`
  (table `user_profiles`, RPC `profile_set_tags`, `get_user_activity_stats` v4 with
  `profile_tags`) — apply after `studylion_port.sql`; until then the card renders with the
  tags row empty and saving tags reports the DB error.
- **Bot-identity guard** — `main.py` now verifies at startup that the logged-in
  Discord ID is Momentum (`1468726880395067412`, `config.MOMENTUM_BOT_ID`) and
  refuses to run under any other token — e.g. SIADLAXITY (`1363266006516105456`),
  the separate siadlak.VIP portal bot — preventing the silent "wrong bot /
  Missing Access" confusion. Also corrected the stale "SIADLAXITY" title in
  `Momentum_Bot_Documentation.md`.
- **StudyLion port, wave 1** (spec: `docs/superpowers/specs/2026-07-11-studylion-port-design.md`;
  requires `scripts/studylion_port.sql` in Supabase — everything degrades gracefully until applied):
  - **Monety** 🪙 — ledger-backed coin economy (`coin_transactions` + `user_activities.coins`,
    floor 0): earned for voice time (50/h, ≤16h/day), todo tasks (50, ≤10/24h), `/done`
    (+10, 1×/aktywność/dzień), GM (+10), rank-ups; spent in the shop; `/portfel`,
    `/przelew`, `/monety-admin`.
  - **`/todo`** — flat per-user tasklist with StudyLion semantics: stable numbering, range ops
    (`1,3-5`, `all`), strikethrough completed, soft delete, `rewarded` flag (no double-pay),
    author-locked toggle select.
  - **`/przypomnij` + `/przypomnienia`** — DM reminders (relative `za:` or Warsaw wall-clock `o:`),
    repeats ≥10 min with anchored advance past missed occurrences, upfront DM-ability probe,
    send-then-ack polling (1m), failures flagged never retried.
  - **`/pomodoro`** — per-voice-channel focus/break timer on StudyLion's `last_started` model
    (resumes mid-cycle after restart), live `<t:…:R>` countdowns in the VC text chat instead of
    rate-limited channel renames, auto-stop on empty + auto-restart on join.
  - **Voice tracking** — all voice channels into `voice_time_daily` (Warsaw days) with idempotent
    coin minting; **`/statystyki`** (today/week/month/all-time + wallet/tasks/activities/GM);
    **`/rangi`** voice-hour rank ladder (config `VOICE_RANKS`, dormant until filled);
    **`/sklep`** colour-role shop (`/sklep-admin` manages items, no deploy needed).
  - `/leaderboard` gains 🪙 Monety (earned this month, transfers excluded) and 🎙️ Głosowe
    (month voice time); the progress card gains 🎙️/✅/🪙 rows.
  - New pure helpers `parsers.py` + `pomodoro_math.py` with stdlib-unittest tests (`tests/`).
  - Deliberately not ported: moderation/video enforcement, premium/gems/sponsors/topgg, skins
    (needs StudyLion's external image-render service), multi-guild config UIs, translations —
    rationale in the spec.
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
