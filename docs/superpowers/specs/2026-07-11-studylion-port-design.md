# StudyLion feature port — design

**Date:** 2026-07-11 · **Status:** wave 1 implemented (this session) ·
**Request:** "Visit github.com/StudyLions/StudyLion, recreate all the features in Momentum bot."

## Problem

StudyLion (LION) is a large multi-tenant study bot: voice-time tracking + statistics,
to-do lists, reminders, pomodoro timers, a full coin economy (shop, private rented
rooms, scheduled accountability sessions, role menus, ranks), plus platform plumbing
(premium/gems, top.gg, sponsors, translations, per-guild config UIs, moderation).
Momentum is a single-server Polish community bot on Supabase RPCs. "Recreate all the
features" therefore means: **recreate every feature that makes sense for this server,
in Momentum's own idioms**, and document what was deliberately not ported and why.

## Approaches considered

1. **Native re-implementation (chosen).** Re-create behaviors as Momentum-style cogs +
   Supabase RPCs, Polish UX, `config.py` knobs, embeds instead of StudyLion's rendered
   PNG cards. Pros: consistent with the running bot, maintainable by one person,
   deployable with the existing `apply SQL → pull → restart` routine. Cons: not a
   literal 1:1 port — gaps are documented below.
2. **Fork/port StudyLion's architecture** (its ORM/registry/config framework/GUI render
   service). Rejected: tens of thousands of lines, PostgreSQL-direct (Momentum has no
   direct SQL, only RPC), English-first, needs a separate image-render service.
3. **Run StudyLion side-by-side** as a second bot. Rejected: English UX, separate
   Postgres, zero integration with Momentum data (coins/streaks/progress card),
   double ops burden.

Licensing note: StudyLion is GPL; behaviors were studied and re-implemented fresh in
Momentum's style (no code copied), which is also what the different data layer forces.

## Scope decision

**Wave 1 (this change):** economy core, tasklist, reminders, pomodoro, voice-time
tracking + `/statystyki`, activity ranks, colour-role shop, and extensions to
`/leaderboard` + the unified progress card. Follow-up in the same wave: profile
cards (`/profil`, section 8) — flagged as missing against StudyLion's README
(`!stats`/`!setprofile`) after the initial cut.

**Wave 2 (spec'd here, not built):** private rented rooms, scheduled accountability
sessions, role menus, text/message XP, weekly & monthly goals, seasons.

**Not porting (rationale):**
- *moderation, video_channels (camera enforcement), studybans* — punitive tooling,
  wrong fit for a small trusted coaching community.
- *premium/gems, sponsors, topgg, skins* — monetization/platform plumbing; skins also
  require StudyLion's external GUI render service (Momentum uses embeds).
- *config framework, user_config timezone, translations* — single guild, single
  timezone (Europe/Warsaw), Polish-only; `config.py` is the config surface.
- *member_admin* — Momentum already has invite-based role assignment.
- *meta (/help), sysadmin* — Discord's native slash-command UI + `/momentum-reboot`.
- *achievements, /now activity tags, voice alerts* — achievements are display-only
  upstream; voice alerts conflict with the recorder (one voice connection per guild).

## Architecture — shared foundation

### Coins ("monety", 🪙)

- `user_activities.coins BIGINT DEFAULT 0` — balance column on the existing per-user row.
- `coin_transactions(id, discord_id, amount, reason, metadata jsonb, created_at)` —
  append-only ledger; **every** balance change goes through it. Reasons: `voice`,
  `task`, `done`, `gm`, `rank`, `transfer_out`, `transfer_in`, `shop`, `admin`.
- RPC `adjust_coins(p_discord_id, p_amount, p_reason, p_metadata)` → `{ok, balance}`.
  Creates the user row if missing; **floors balance at 0** (StudyLion's known negative-
  balance hole is deliberately closed): a debit that would go below zero returns
  `{ok:false}` and writes nothing.
- RPC `transfer_coins(p_from, p_to, p_amount)` — atomic (one plpgsql tx): balance
  check, two ledger rows, two balance updates.

Earning (defaults mirror StudyLion where it has one):

| Source | Amount | Cap |
|---|---|---|
| Voice time | 50/h, pro-rated per second (`VOICE_COINS_PER_HOUR`) | 16 h/day (`VOICE_COIN_DAILY_CAP_HOURS`, Warsaw day) |
| Completed task | 50 (`TASK_REWARD_COINS`) | 10 rewarded tasks / rolling 24 h (`TASK_REWARD_LIMIT_24H`) |
| `/done` activity | 10 (`DONE_REWARD_COINS`) | once per activity per Warsaw day (`award_activity_coins`; streaks stay uncapped, only coins are gated) |
| GM check-in | 10 (`GM_REWARD_COINS`) | 1/day (check-in itself is 1/day) |
| Rank-up | per-rank `reward` from `VOICE_RANKS` | once per threshold (persisted) |

Anti-double-mint: the ledger is the source of truth — voice minting computes "coins
already minted today" as `SUM(amount) WHERE reason='voice' AND Warsaw-day = today`;
task rewards count `reason='task'` rows in the last 24 h; rank rewards persist the
highest awarded threshold in `user_rank_state`.

Commands (cogs/economy.py): `/portfel [użytkownik]` — balance + this month's earnings
(public embed, house progress culture; upstream gates balance behind mods — dropped);
`/przelew <komu> <ile>` — mirrors upstream `/send`: min 1, no fee, blocks self/bots,
atomic RPC, best-effort DM notice to the recipient; `/monety-admin <komu> <ile>` —
owner-only grant/deduction (`reason='admin'`), the minimal slice of upstream's
`/economy balance set/add`.

### SQL delivery

Everything lands in **`scripts/studylion_port.sql`** (idempotent: `CREATE TABLE IF NOT
EXISTS` + `CREATE OR REPLACE FUNCTION`, RLS + service-role policies like the existing
tables), and is mirrored into the canonical `supabase_schema.sql`. Until the script is
applied in Supabase, every new command degrades to the standard ephemeral Polish error
(house pattern from the unified-leaderboard rollout); the voice tracker just logs.

### New helper modules (pure, unit-tested, no discord imports)

- `parsers.py` — `parse_duration_pl("1d 2h 30m" | "90" → minutes)` (units d/h/m/s,
  bare int = minutes, mirrors StudyLion's `DurationTransformer(60)`),
  `parse_wallclock_pl("16:00" | "2026-07-12 09:00")` (Warsaw; bare HH:MM rolls to
  tomorrow when past), `parse_index_ranges("1,3-5,8" | "all"/"-" → indices)`.
- `pomodoro_math.py` — `current_stage(last_started, focus_s, break_s, now)` →
  `(stage, stage_start, stage_end)`; the whole cycle derives from the `last_started`
  anchor (StudyLion's model), so state survives restarts by construction.

Tests: `tests/test_parsers.py`, `tests/test_pomodoro_math.py` — stdlib `unittest`,
runnable with system python3 (no venv on the dev machine).

## Architecture — features

### 1. Tasklist — `/todo` (cogs/todo.py)

Flat per-user list (StudyLion's subtask tree + cycle-pruning deliberately dropped —
YAGNI at this community's scale; wave 2 can add `parent_id`).

- Table `todo_items(id, discord_id, content ≤100, completed_at, rewarded bool,
  created_at, updated_at, deleted_at)` — soft delete, like upstream.
- Numbering = 1-based position in the live list ordered by `id` (stable across
  renders because completed tasks stay listed, struck through, until removed).
- Subcommands: `dodaj <treść>` (also `;`-separated bulk), `lista`, `zrobione <numery>`,
  `cofnij <numery>`, `usun <numery|all>`, `wyczysc`, `edytuj <numer> <treść>`.
  `<numery>` accepts `1`, `1,3`, `2-5`, `all`/`-` (parse_index_ranges).
- `lista` embed: `N/M ukończone` header, `~~strikethrough~~` for done, ≤40 lines with
  "…i N kolejnych" overflow note; plus an author-locked select menu (≤25 open tasks,
  10-min timeout) that toggles completion — the one interactive piece kept from
  StudyLion's widget.
- Rewards: RPC `todo_set_done` marks tasks and, inside the same function, rewards the
  still-unrewarded ones up to the rolling-24 h limit (one ledger row per task,
  `metadata.task_id`), sets `rewarded=true`. Un-ticking never claws back (upstream
  behavior). Reply mentions `+N 🪙` when coins were minted.
- Caps: 100 open tasks (`TODO_MAX_TASKS`), content 100 chars.

### 2. Reminders — `/przypomnij`, `/przypomnienia` (cogs/reminders.py)

- Table `reminders(id, discord_id, content ≤2000, remind_at, every_seconds int null,
  failed bool default false, created_at)` — hard delete on cancel/fire (upstream).
- `/przypomnij tekst:<...> [za:<czas>] [o:<godzina|data>] [co:<czas>]` — exactly one of
  `za`/`o`; `co` = repeat, min 600 s. Validations mirror upstream: future-only, ≤25
  per user, DM-ability probe at creation (`user.send('')` → `Forbidden` means DMs
  closed → refuse with instructions; the always-failing empty send costs nothing).
- `/przypomnienia [usun:<numer|all>]` — numbered list (by `created_at`), cancel.
- Delivery: DM-only (privacy — no channel fallback, upstream behavior). Poller is a
  1-minute `tasks.loop` (house idiom; fires ≤60 s late, documented): RPC
  `reminders_due()` returns due+unfailed rows *without* mutating; after each send the
  cog acks via `reminder_ack(id, ok)` — repeating: `remind_at += every` advanced past
  all missed occurrences (anchored to the original time — StudyLion's anti-burst,
  anti-drift logic, done in SQL); one-shot: delete; failure: `failed=true`, never
  retried. Send-then-ack means a crash re-sends rather than silently losing one.
- Delivered embed: orange, "Prosiłeś/aś o przypomnienie!", content, `Następne: <t:R>`
  when repeating.

### 3. Pomodoro — `/pomodoro` (cogs/pomodoro.py)

- Table `pomodoro_timers(channel_id PK, focus_seconds, break_seconds, last_started
  timestamptz null, auto_restart bool, started_by, created_at)`.
- `/pomodoro start [fokus:<min=25>] [przerwa:<min=5>]` — binds to the caller's voice
  channel; running timer restarts with the new lengths. `/pomodoro stop`,
  `/pomodoro status` (ephemeral: stage, `<t:…:R>` live countdown, pattern, members).
- Loop per timer (asyncio task, chunked sleep ≤5 min): on each stage boundary post to
  the **voice channel's built-in text chat**: stage line (`🍅 Fokus do <t:R>` /
  `☕ Przerwa do <t:R>`) + spoiler-wrapped member mentions (upstream pattern). Also
  best-effort `channel.edit(status=...)` so the stage shows on the channel — wrapped
  in try/except (API/perm differences must never kill the loop).
- Empty channel at a stage boundary → stop with `auto_restart=true`; next join
  restarts the cycle (upstream `auto_restart`). Manual stop clears it.
- Restart-proof: `last_started` anchor + `pomodoro_math.current_stage` recompute the
  stage on `on_ready`; running timers resume mid-cycle (upstream model).
- Dropped vs upstream (documented): VC renames with countdown (Discord's 2/10 min
  rename limit made even StudyLion's laggy — `<t:R>` gives a real live countdown),
  audio alerts (voice client owned by the recorder), Present-button inactivity kicks
  (wrong fit), manager roles/owned timers (single trusted community: anyone in the
  channel controls its timer).

### 4. Voice tracking + `/statystyki` (cogs/voice_tracker.py, cogs/statystyki.py)

- Table `voice_time_daily(discord_id, day, channel_id, seconds)` PK(discord_id, day,
  channel_id) — per-Warsaw-day aggregates instead of upstream's session rows (Momentum
  has no session-timeline graphics; aggregates keep the RPC surface tiny). Days are
  Warsaw — same anti-abuse reasoning as upstream's guild-timezone rule.
- Cog mirrors `session_tracker`'s proven shape: refs dict, `on_ready` seeding of
  already-connected members, join/leave/move flush, periodic 5-min flush loop (bounds
  restart loss to <5 min; upstream's fancier downtime reconciliation not needed).
  All voice channels tracked except `UNTRACKED_VOICE_CHANNEL_IDS` and bots.
- RPC `add_voice_time(p_discord_id, p_channel_id, p_seconds, p_coins_per_hour,
  p_daily_cap_seconds)` — upserts the aggregate and mints coins for the capped delta
  (ledger-diff idempotency); returns `{day_seconds, total_seconds, coins_minted}`.
- After each flush the cog dispatches `momentum_voice_flushed(member, total_seconds)`
  — the ranks cog listens (decoupling, discord.py-idiomatic).
- RPC `get_voice_stats(p_discord_id)` → today/this-week/this-month/all-time seconds
  (Warsaw boundaries; week = Monday).
- `/statystyki [użytkownik]` — public embed (Momentum's progress culture): 🎙️ voice
  today/week/month/total, 🪙 balance, ✅ tasks (open + done), the four activities,
  🔢 Daily Coaching, ⚓️ Deep Work, ☀️ GM (total + momentum). Deep Work seconds remain
  their own lifetime metric *and* count in generic voice time — different measures,
  labeled as such.

### 5. Ranks (cogs/ranks.py)

- Config `VOICE_RANKS: list[(hours, role_id, reward_coins)]` — empty by default →
  cog stays dormant (server owner fills real role IDs; StudyLion's 7-level template
  ladder 1 h → 80 h with 1000→7000 coin rewards is the documented example in
  config.py comments).
- On `momentum_voice_flushed`: deserved rank = highest threshold ≤ lifetime hours;
  grants the role, removes other rank-ladder roles (upstream award-highest/remove-
  others), announces in the progress channel (Momentum celebrates publicly — upstream
  DM default dropped), and mints the rank's reward once per threshold via
  `record_rank_award(p_discord_id, p_hours)` (insert-guard table `user_rank_state`).
- `/rangi` — ladder + caller's lifetime hours and progress to the next rank.
- Lifetime (no seasons) — single community; seasons are wave 2.

### 6. Shop — `/sklep` (cogs/shop.py)

- Table `shop_items(id, role_id unique, name, price, active, created_at, deleted_at)`
  — DB-driven so adding colours needs no deploy. The Discord role itself is the
  inventory (single-slot colour, upstream semantics); the ledger records purchases
  (`reason='shop'`, `metadata.role_id`).
- `/sklep` — embed of items + select menu → buy: `adjust_coins` debit (atomic floor
  check), remove other shop colour roles, grant the new one. "No refunds on swap"
  warning, upstream wording.
- `/sklep-admin dodaj <rola> <cena>` / `usun <rola>` / `lista` — `manage_guild` only.
  Existing roles only (upstream's create-role-from-hex flow dropped: one server, the
  owner creates roles by hand); refuses roles with admin perms or above the bot's top
  role.

### 7. Cross-cutting extensions

- `/leaderboard` gains 🪙 **Monety** (coins *earned* this Warsaw month, positive
  ledger sum excluding `transfer_in` and positive `shop` rows, i.e. refunds —
  monthly spirit of the existing board; balances aren't monthly) and 🎙️ **Głosowe**
  (this month's voice seconds; the cog renders seconds via `format_duration_pl`).
  Same RPC shape, two new branches.
- `get_user_activity_stats` v3 additionally returns `coins`, `voice_seconds_total`,
  `tasks_done_total`, `tasks_open`, `gm_total`, `gm_momentum` — feeds both
  `/statystyki` and the unified progress card (new auto-hidden rows: 🪙 Monety,
  🎙️ Głosowe, ✅ Zadania).
- `cogs/done.py` and both GM paths (`gm.py`, `gmlistener.py`) get a 2-line
  best-effort `adjust_coins` award (`+10`) after a successful log — wrapped so
  economy failure never breaks the existing flows.

### 8. Profile cards — `/profil` (cogs/profil.py, follow-up)

Upstream: `/me` profile card with free-text "profile badges" (`member_profile_tags`,
≤5, edited via modal) rendered as a PNG; old-README `!setprofile`. Momentum port:

- Table `user_profiles(discord_id PK, tags text[])` + RPC `profile_set_tags`
  (≤`PROFILE_MAX_TAGS`=5 tags × ≤`PROFILE_TAG_MAX_LEN`=30 chars, validated in the
  cog via the pure `parse_profile_tags` helper AND server-side); delivered as
  `scripts/profile_tags.sql` (separate incremental script since
  `studylion_port.sql` may already be applied), which also redefines
  `get_user_activity_stats` (v4: + `profile_tags`).
- `/profil [użytkownik]` — identity-focused embed (tags, rank + next-rank
  progress from `VOICE_RANKS`, monety, lifetime voice, GM momentum) — the
  numbers-heavy detail stays in `/statystyki`. Self-view attaches an
  author-locked "Edytuj tagi" button → modal prefilled with current tags
  (upstream's Edit Profile Badges flow). Public embed, house culture; upstream's
  "private card" framing dropped like the other PNG-card features.
- Achievements strip from the upstream card stays unported (display-only
  upstream; see "Not porting").

## Wave 2 blueprints (not built; upstream behavior captured for later)

- **Private rooms**: rent a VC (1000 🪙/day default), room bank pays daily rent,
  deposit to extend, invite/kick/transfer, overwrites, soft delete, restart re-ticks.
- **Schedule**: hourly slots, 100 🪙 booking, attendance ≥10 min in tracked channels,
  200 🪙 reward +200 group bonus if everyone shows, no-show cancels future bookings
  without refund (+optional blacklist role).
- **Rolemenus**: button/dropdown/reaction menus, per-role price/duration/required-role,
  sticky/refunds/obtainable caps.
- **Text XP**: 5-min activity periods (upstream ships debug 10 s values — use 5 min),
  XP→coins at 50/100 XP; skipped in wave 1 for chat-farming concerns.
- **Goals**: weekly/monthly task/hour targets, motivational only (no rewards upstream).

## Rollout & degradation

1. Apply `scripts/studylion_port.sql` in Supabase (idempotent).
2. `git pull` on the server, restart per CLAUDE.md.
3. Fill `VOICE_RANKS` and `/sklep-admin dodaj` items whenever desired — both features
   are safely dormant until then.

Code-before-SQL degradation: commands answer with the standard ephemeral Polish error;
voice tracker and reminder poller log and continue; nothing crashes. New cogs are
additive — no existing cog's behavior changes except the two-line coin hooks and the
extended (backwards-compatible) stats RPC.

## Testing

- `python3 -m unittest discover tests` — parsers + pomodoro stage math (pure logic).
- `python3 -m py_compile` on every touched file (no venv on the dev Mac; discord.py
  imports are compile-checked only).
- Manual after deploy: `/todo dodaj|lista|zrobione`, `/przypomnij za:1m`, `/pomodoro
  start fokus:1 przerwa:1` in a test VC, `/portfel`, `/przelew`, `/sklep-admin dodaj`,
  `/leaderboard` new categories, `/statystyki`, voice join → flush row in
  `voice_time_daily`.
