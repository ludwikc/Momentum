# Unified leaderboard — design

**Date:** 2026-07-11 · **Status:** implemented (follow-up to
`2026-07-03-unified-progress-card-design.md`; user asked to unify the leaderboard the
same way and to drop the dead `get_deep_work_seconds` wrapper)

## Problem

`/leaderboard` only offered the four self-reported activities. Daily Coaching and Deep
Work — both on the unified progress card — had no leaderboard at all.

## Decisions

- `/leaderboard` offers all six progress-card categories: trening, medytacja, sukces,
  dziennik, 🔢 Daily Coaching, ⚓️ Deep Work.
- **Ranking stays monthly for everything** (consistent with the existing streak_*-based
  ranking): the two join-based categories rank by this month's `activity_logs` rows
  (Warsaw-local month). Deep Work ranks by session count, not banked time —
  `deep_work_seconds` is lifetime-only, so a time ranking couldn't be monthly.
- `get_deep_work_seconds` wrapper removed from `db.py` (unused since the unified card
  reads time via `get_user_activity_stats`). The SQL function stays in the schema in
  case anything outside the bot calls it.

## Architecture

**SQL** — `scripts/unified_leaderboard.sql` replaces `get_activity_leaderboard`: an
`IF p_activity IN ('daily_coaching','deep_work')` branch counts this month's
`activity_logs` rows per user (same return shape: `rank, discord_id, streak_count,
user_id`); the ELSE branch keeps the existing dynamic `streak_%I` query verbatim.
Canonical copy updated in `supabase_schema.sql`.

**Cog** — `cogs/leaderboard.py` replaces the local `act` dict with `CATEGORIES`
(value → emoji + display label, needed because `"daily_coaching".capitalize()` renders
badly). Embed title uses the label; everything else unchanged.

## Rollout & degradation

Code first, SQL after: if `unified_leaderboard.sql` isn't applied yet, picking one of
the two new categories makes the old RPC error on `streak_daily_coaching` /
`streak_deep_work` — the cog's existing try/except catches it and replies with the
ephemeral error message. No crash, but the feature needs the SQL to work. Order:
apply SQL in Supabase → pull + restart bot.

## Testing

- `py_compile` on `db.py`, `cogs/leaderboard.py`.
- Smoke test (scratch venv with discord.py, `db` stubbed): all six slash-command
  choices register with correct labels/values.
- Manual after deploy: `/leaderboard` → Deep Work and Daily Coaching return this
  month's rankings; empty categories show "Brak wyników".
