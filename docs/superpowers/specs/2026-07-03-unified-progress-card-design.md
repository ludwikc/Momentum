# Unified progress card — design

**Date:** 2026-07-03 · **Status:** approved by Ludwik (AskUserQuestion, this session)

## Problem

Posts on the progress channel (`PROGRESS_CHANNEL_ID = 1225131519404675124`) come in three
disjoint shapes: the shared "Aktywność" embed for self-reported activities (`/done`,
photo-proof trening, Tuesday meditation), and two ad-hoc embeds built inside
`session_tracker.py` for Daily Coaching joins and Deep Work joins. A user's stats are
scattered across post types instead of appearing on one card.

## Decisions (confirmed with user)

1. **Every post is the full card.** Each event still creates a new post (channel stays a
   feed); the embed always shows the user's complete stats.
2. **Deep Work row shows time + session count:** `⚓️ Deep Work: 12 godzin i 30 minut (45 sesji)`.
3. **Counters are lifetime; the headline is monthly** (same convention as today's `/done`
   embed: "To N … w tym miesiącu!", lifetime totals below).

## Card layout

```
Aktywność                                  [avatar thumbnail]
<headline — event-specific, examples below>
💪 Trening: 3
🧘 Medytacja: 12
💎 Sukces: 5
📝 Dziennik: 1
🔢 Daily Coaching: 17
⚓️ Deep Work: 12 godzin i 30 minut (45 sesji)
```

Zero rows are omitted (existing behaviour, extended to the two new rows).

Headlines by trigger (unchanged wording):
- activity log: `🔥 To 3 medytacja w tym miesiącu!` + ` (5 z rzędu!)` when consecutive > 2
- Daily Coaching join: `To 4 Daily Coaching w tym miesiącu.`
- Deep Work join: `To 2 sesja Deep Work w tym miesiącu.`

## Architecture

**One stats source.** Extend the `get_user_activity_stats` RPC (Supabase) to additionally
return:
- `total_daily_coaching` — lifetime count of `activity_logs` rows with `activity_type = 'daily_coaching'`
- `total_deep_work` — lifetime count of `deep_work` rows (sessions)
- `deep_work_seconds` — from `user_activities.deep_work_seconds`

Delivered as `scripts/unified_progress_stats.sql` (pattern: `scripts/coaching_limit.sql`),
applied manually in the Supabase SQL editor.

**One embed builder.** `activity_embed.py` gains `build_progress_embed(user, headline,
all_stats)` that renders the full card. The existing `build_activity_embed(user,
activity_type, result, all_stats)` becomes a thin wrapper: builds the activity headline
(monthly count + consecutive) and delegates. `_plural_pl` and `format_duration_pl` move
from `session_tracker.py` into `activity_embed.py` (the card builder needs them);
`session_tracker` imports `format_duration_pl` from there.

**Call sites.**
- `done.py`, `photo_reply.py`, `meditation_voice.py`: unchanged signatures — they already
  pass `get_user_activity_stats` output; the card grows the two new rows automatically.
- `session_tracker.py`: drops its private `_post` embed construction; on a logged join it
  fetches `get_user_activity_stats` and posts `build_progress_embed` with the
  event headline (still `content=member.mention`).

## Rollout & degradation

Builder reads the new keys with `.get(..., 0)`. If the SQL hasn't been applied yet, the
card simply lacks the Daily Coaching / Deep Work rows — no crash. Order: commit code →
apply SQL in Supabase → restart bot on the server (`/root/Momentum`, venv python).

## Testing

- `venv/bin/python -m py_compile` on touched files (repo has no test framework).
- Manual: `/done` post shows all rows; Deep Work / Daily Coaching joins post the same card
  with their headlines; user with zero DC/DW sees no empty rows.
