-- =============================================================================
-- STUDYLION PORT — WAVE 1 (2026-07)
-- Coins economy, todo list, reminders, voice-time tracking, pomodoro timers,
-- colour-role shop, rank-award state + extended stats/leaderboard RPCs.
-- Spec: docs/superpowers/specs/2026-07-11-studylion-port-design.md
--
-- Idempotent: safe to run more than once in the Supabase SQL editor.
-- =============================================================================

-- =============================================================================
-- A. TABLES
-- =============================================================================

-- Coin balance lives on the existing per-user row.
ALTER TABLE user_activities ADD COLUMN IF NOT EXISTS coins BIGINT NOT NULL DEFAULT 0;

-- Append-only ledger: every balance change goes through it. It is also the
-- anti-double-mint source of truth (voice minting, task-reward 24h window).
CREATE TABLE IF NOT EXISTS coin_transactions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    discord_id TEXT NOT NULL,
    amount BIGINT NOT NULL,
    reason TEXT NOT NULL CHECK (
        reason IN ('voice', 'task', 'done', 'gm', 'rank',
                   'transfer_in', 'transfer_out', 'shop', 'admin')
    ),
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_coin_tx_discord_reason_at
    ON coin_transactions(discord_id, reason, created_at);
CREATE INDEX IF NOT EXISTS idx_coin_tx_created_at ON coin_transactions(created_at);

-- Flat per-user todo list (soft delete, StudyLion semantics).
CREATE TABLE IF NOT EXISTS todo_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    discord_id TEXT NOT NULL,
    content TEXT NOT NULL CHECK (char_length(content) BETWEEN 1 AND 100),
    completed_at TIMESTAMPTZ,
    rewarded BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_todo_items_owner_live
    ON todo_items(discord_id) WHERE deleted_at IS NULL;

-- DM reminders (hard delete on cancel/fire; failed ones are kept + flagged).
CREATE TABLE IF NOT EXISTS reminders (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    discord_id TEXT NOT NULL,
    content TEXT NOT NULL CHECK (char_length(content) BETWEEN 1 AND 2000),
    remind_at TIMESTAMPTZ NOT NULL,
    every_seconds INTEGER,
    failed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_reminders_due
    ON reminders(remind_at) WHERE failed = FALSE;
CREATE INDEX IF NOT EXISTS idx_reminders_owner ON reminders(discord_id);

-- Per-Warsaw-day voice-time aggregates (all tracked voice channels).
CREATE TABLE IF NOT EXISTS voice_time_daily (
    discord_id TEXT NOT NULL,
    day DATE NOT NULL,
    channel_id TEXT NOT NULL,
    seconds BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (discord_id, day, channel_id)
);
CREATE INDEX IF NOT EXISTS idx_voice_time_daily_day ON voice_time_daily(day);

-- Pomodoro timers: the whole cycle derives from last_started (NULL = stopped).
CREATE TABLE IF NOT EXISTS pomodoro_timers (
    channel_id TEXT PRIMARY KEY,
    focus_seconds INTEGER NOT NULL CHECK (focus_seconds > 0),
    break_seconds INTEGER NOT NULL CHECK (break_seconds > 0),
    last_started TIMESTAMPTZ,
    auto_restart BOOLEAN NOT NULL DEFAULT FALSE,
    started_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Colour-role shop items (DB-driven so adding colours needs no deploy).
CREATE TABLE IF NOT EXISTS shop_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    role_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price BIGINT NOT NULL CHECK (price >= 0),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- Highest rank threshold (in hours) already rewarded per user, so a rank's
-- coin reward is minted exactly once even if roles get juggled manually.
CREATE TABLE IF NOT EXISTS user_rank_state (
    discord_id TEXT PRIMARY KEY,
    awarded_hours INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- B. ROW LEVEL SECURITY (service role only, same as the existing tables)
-- =============================================================================

ALTER TABLE coin_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE todo_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE reminders ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_time_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE pomodoro_timers ENABLE ROW LEVEL SECURITY;
ALTER TABLE shop_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_rank_state ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_coin_transactions" ON coin_transactions;
CREATE POLICY "service_role_all_coin_transactions" ON coin_transactions
    FOR ALL USING (auth.role() = 'service_role');
DROP POLICY IF EXISTS "service_role_all_todo_items" ON todo_items;
CREATE POLICY "service_role_all_todo_items" ON todo_items
    FOR ALL USING (auth.role() = 'service_role');
DROP POLICY IF EXISTS "service_role_all_reminders" ON reminders;
CREATE POLICY "service_role_all_reminders" ON reminders
    FOR ALL USING (auth.role() = 'service_role');
DROP POLICY IF EXISTS "service_role_all_voice_time_daily" ON voice_time_daily;
CREATE POLICY "service_role_all_voice_time_daily" ON voice_time_daily
    FOR ALL USING (auth.role() = 'service_role');
DROP POLICY IF EXISTS "service_role_all_pomodoro_timers" ON pomodoro_timers;
CREATE POLICY "service_role_all_pomodoro_timers" ON pomodoro_timers
    FOR ALL USING (auth.role() = 'service_role');
DROP POLICY IF EXISTS "service_role_all_shop_items" ON shop_items;
CREATE POLICY "service_role_all_shop_items" ON shop_items
    FOR ALL USING (auth.role() = 'service_role');
DROP POLICY IF EXISTS "service_role_all_user_rank_state" ON user_rank_state;
CREATE POLICY "service_role_all_user_rank_state" ON user_rank_state
    FOR ALL USING (auth.role() = 'service_role');

-- =============================================================================
-- C. ECONOMY RPCs
-- =============================================================================

-- Ensure the per-user row exists (shared helper for the functions below).
CREATE OR REPLACE FUNCTION _ensure_user_activities(p_discord_id TEXT)
RETURNS VOID AS $$
BEGIN
    INSERT INTO user_activities (discord_id, last_reset)
    VALUES (p_discord_id, DATE_TRUNC('month', CURRENT_DATE)::date)
    ON CONFLICT (discord_id) DO NOTHING;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Single entry point for every balance change. Floors the balance at 0:
-- a debit that would go negative returns ok=false and writes nothing.
CREATE OR REPLACE FUNCTION adjust_coins(
    p_discord_id TEXT,
    p_amount BIGINT,
    p_reason TEXT,
    p_metadata JSONB DEFAULT NULL
)
RETURNS JSON AS $$
DECLARE
    v_balance BIGINT;
BEGIN
    PERFORM _ensure_user_activities(p_discord_id);

    SELECT coins INTO v_balance
    FROM user_activities WHERE discord_id = p_discord_id
    FOR UPDATE;

    IF p_amount < 0 AND v_balance + p_amount < 0 THEN
        RETURN json_build_object('ok', false, 'error', 'insufficient',
                                 'balance', v_balance);
    END IF;

    UPDATE user_activities
    SET coins = coins + p_amount, updated_at = NOW()
    WHERE discord_id = p_discord_id
    RETURNING coins INTO v_balance;

    INSERT INTO coin_transactions (discord_id, amount, reason, metadata)
    VALUES (p_discord_id, p_amount, p_reason, p_metadata);

    RETURN json_build_object('ok', true, 'balance', v_balance);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Balance + earnings summary for /portfel.
CREATE OR REPLACE FUNCTION get_coin_summary(p_discord_id TEXT)
RETURNS JSON AS $$
DECLARE
    v_balance BIGINT;
    v_earned_month BIGINT;
    v_earned_total BIGINT;
    v_month_start DATE := DATE_TRUNC('month', (NOW() AT TIME ZONE 'Europe/Warsaw'))::date;
BEGIN
    SELECT coins INTO v_balance FROM user_activities WHERE discord_id = p_discord_id;

    SELECT
        COALESCE(SUM(amount) FILTER (
            WHERE (created_at AT TIME ZONE 'Europe/Warsaw')::date >= v_month_start), 0),
        COALESCE(SUM(amount), 0)
    INTO v_earned_month, v_earned_total
    FROM coin_transactions
    WHERE discord_id = p_discord_id AND amount > 0 AND reason <> 'transfer_in';

    RETURN json_build_object(
        'balance', COALESCE(v_balance, 0),
        'earned_month', v_earned_month,
        'earned_total', v_earned_total
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Atomic member→member transfer (no fee, min 1; mirrors StudyLion /send).
CREATE OR REPLACE FUNCTION transfer_coins(
    p_from TEXT,
    p_to TEXT,
    p_amount BIGINT
)
RETURNS JSON AS $$
DECLARE
    v_from_balance BIGINT;
    v_to_balance BIGINT;
BEGIN
    IF p_amount < 1 THEN
        RETURN json_build_object('ok', false, 'error', 'invalid_amount');
    END IF;
    IF p_from = p_to THEN
        RETURN json_build_object('ok', false, 'error', 'self');
    END IF;

    PERFORM _ensure_user_activities(p_from);
    PERFORM _ensure_user_activities(p_to);

    -- Lock both rows in a consistent order to avoid deadlocks.
    PERFORM 1 FROM user_activities
    WHERE discord_id IN (p_from, p_to)
    ORDER BY discord_id
    FOR UPDATE;

    SELECT coins INTO v_from_balance FROM user_activities WHERE discord_id = p_from;
    IF v_from_balance < p_amount THEN
        RETURN json_build_object('ok', false, 'error', 'insufficient',
                                 'balance', v_from_balance);
    END IF;

    UPDATE user_activities SET coins = coins - p_amount, updated_at = NOW()
    WHERE discord_id = p_from RETURNING coins INTO v_from_balance;
    UPDATE user_activities SET coins = coins + p_amount, updated_at = NOW()
    WHERE discord_id = p_to RETURNING coins INTO v_to_balance;

    INSERT INTO coin_transactions (discord_id, amount, reason, metadata) VALUES
        (p_from, -p_amount, 'transfer_out', jsonb_build_object('to', p_to)),
        (p_to, p_amount, 'transfer_in', jsonb_build_object('from', p_from));

    RETURN json_build_object('ok', true, 'from_balance', v_from_balance,
                             'to_balance', v_to_balance);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- D. TODO RPCs
-- =============================================================================

CREATE OR REPLACE FUNCTION todo_add(
    p_discord_id TEXT,
    p_items TEXT[],
    p_max_open INTEGER DEFAULT 100
)
RETURNS JSON AS $$
DECLARE
    v_open INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_open
    FROM todo_items
    WHERE discord_id = p_discord_id AND deleted_at IS NULL
      AND completed_at IS NULL;

    IF v_open + COALESCE(array_length(p_items, 1), 0) > p_max_open THEN
        RETURN json_build_object('ok', false, 'error', 'limit',
                                 'open_count', v_open);
    END IF;

    INSERT INTO todo_items (discord_id, content)
    SELECT p_discord_id, item FROM unnest(p_items) AS item;

    RETURN json_build_object('ok', true,
                             'added', COALESCE(array_length(p_items, 1), 0),
                             'open_count', v_open + COALESCE(array_length(p_items, 1), 0));
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION todo_list(p_discord_id TEXT)
RETURNS JSON AS $$
BEGIN
    RETURN COALESCE(
        (SELECT json_agg(json_build_object(
                    'id', t.id,
                    'content', t.content,
                    'completed_at', t.completed_at,
                    'created_at', t.created_at
                ) ORDER BY t.id)
         FROM todo_items t
         WHERE t.discord_id = p_discord_id AND t.deleted_at IS NULL),
        '[]'::json
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Tick/untick + reward inside one transaction (StudyLion semantics: reward
-- each task once, at most p_reward_limit_24h rewarded tasks per rolling 24h,
-- unticking never claws back).
CREATE OR REPLACE FUNCTION todo_set_done(
    p_discord_id TEXT,
    p_ids BIGINT[],
    p_done BOOLEAN,
    p_reward_coins INTEGER DEFAULT 50,
    p_reward_limit_24h INTEGER DEFAULT 10
)
RETURNS JSON AS $$
DECLARE
    v_changed INTEGER := 0;
    v_reward_ids BIGINT[];
    v_rewarded INTEGER := 0;
    v_recent INTEGER;
    v_balance BIGINT;
BEGIN
    IF p_done THEN
        WITH changed AS (
            UPDATE todo_items
            SET completed_at = NOW(), updated_at = NOW()
            WHERE discord_id = p_discord_id AND id = ANY(p_ids)
              AND deleted_at IS NULL AND completed_at IS NULL
            RETURNING id, rewarded
        )
        SELECT COUNT(*),
               ARRAY(SELECT id FROM changed WHERE NOT rewarded ORDER BY id)
        INTO v_changed, v_reward_ids
        FROM changed;

        IF COALESCE(array_length(v_reward_ids, 1), 0) > 0 THEN
            SELECT COUNT(*) INTO v_recent
            FROM coin_transactions
            WHERE discord_id = p_discord_id AND reason = 'task'
              AND created_at > NOW() - INTERVAL '24 hours';

            v_rewarded := LEAST(
                COALESCE(array_length(v_reward_ids, 1), 0),
                GREATEST(p_reward_limit_24h - v_recent, 0)
            );

            IF v_rewarded > 0 THEN
                v_reward_ids := v_reward_ids[1:v_rewarded];

                PERFORM _ensure_user_activities(p_discord_id);

                INSERT INTO coin_transactions (discord_id, amount, reason, metadata)
                SELECT p_discord_id, p_reward_coins, 'task',
                       jsonb_build_object('task_id', rid)
                FROM unnest(v_reward_ids) AS rid;

                UPDATE todo_items SET rewarded = TRUE
                WHERE id = ANY(v_reward_ids);

                UPDATE user_activities
                SET coins = coins + (p_reward_coins::BIGINT * v_rewarded),
                    updated_at = NOW()
                WHERE discord_id = p_discord_id;
            END IF;
        END IF;
    ELSE
        WITH changed AS (
            UPDATE todo_items
            SET completed_at = NULL, updated_at = NOW()
            WHERE discord_id = p_discord_id AND id = ANY(p_ids)
              AND deleted_at IS NULL AND completed_at IS NOT NULL
            RETURNING id
        )
        SELECT COUNT(*) INTO v_changed FROM changed;
    END IF;

    SELECT coins INTO v_balance FROM user_activities WHERE discord_id = p_discord_id;

    RETURN json_build_object(
        'ok', true,
        'changed', v_changed,
        'rewarded', v_rewarded,
        'coins_minted', v_rewarded * p_reward_coins,
        'balance', COALESCE(v_balance, 0)
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION todo_remove(p_discord_id TEXT, p_ids BIGINT[])
RETURNS JSON AS $$
DECLARE
    v_removed INTEGER;
BEGIN
    WITH removed AS (
        UPDATE todo_items
        SET deleted_at = NOW(), updated_at = NOW()
        WHERE discord_id = p_discord_id AND id = ANY(p_ids) AND deleted_at IS NULL
        RETURNING id
    )
    SELECT COUNT(*) INTO v_removed FROM removed;

    RETURN json_build_object('ok', true, 'removed', v_removed);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION todo_edit(p_discord_id TEXT, p_id BIGINT, p_content TEXT)
RETURNS JSON AS $$
DECLARE
    v_found BOOLEAN;
BEGIN
    UPDATE todo_items
    SET content = p_content, updated_at = NOW()
    WHERE discord_id = p_discord_id AND id = p_id AND deleted_at IS NULL;
    v_found := FOUND;

    RETURN json_build_object('ok', v_found);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- E. REMINDER RPCs
-- =============================================================================

CREATE OR REPLACE FUNCTION reminder_add(
    p_discord_id TEXT,
    p_content TEXT,
    p_remind_at TIMESTAMPTZ,
    p_every_seconds INTEGER DEFAULT NULL,
    p_max_per_user INTEGER DEFAULT 25,
    p_min_every_seconds INTEGER DEFAULT 600
)
RETURNS JSON AS $$
DECLARE
    v_count INTEGER;
    v_id BIGINT;
BEGIN
    IF p_remind_at <= NOW() THEN
        RETURN json_build_object('ok', false, 'error', 'past');
    END IF;
    IF p_every_seconds IS NOT NULL AND p_every_seconds < p_min_every_seconds THEN
        RETURN json_build_object('ok', false, 'error', 'min_interval');
    END IF;

    SELECT COUNT(*) INTO v_count FROM reminders WHERE discord_id = p_discord_id;
    IF v_count >= p_max_per_user THEN
        RETURN json_build_object('ok', false, 'error', 'limit', 'count', v_count);
    END IF;

    INSERT INTO reminders (discord_id, content, remind_at, every_seconds)
    VALUES (p_discord_id, p_content, p_remind_at, p_every_seconds)
    RETURNING id INTO v_id;

    RETURN json_build_object('ok', true, 'id', v_id, 'count', v_count + 1);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION reminder_list(p_discord_id TEXT)
RETURNS JSON AS $$
BEGIN
    RETURN COALESCE(
        (SELECT json_agg(json_build_object(
                    'id', r.id,
                    'content', r.content,
                    'remind_at', r.remind_at,
                    'every_seconds', r.every_seconds,
                    'failed', r.failed
                ) ORDER BY r.created_at)
         FROM reminders r WHERE r.discord_id = p_discord_id),
        '[]'::json
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION reminder_cancel(p_discord_id TEXT, p_ids BIGINT[])
RETURNS JSON AS $$
DECLARE
    v_removed INTEGER;
BEGIN
    WITH removed AS (
        DELETE FROM reminders
        WHERE discord_id = p_discord_id AND id = ANY(p_ids)
        RETURNING id
    )
    SELECT COUNT(*) INTO v_removed FROM removed;

    RETURN json_build_object('ok', true, 'removed', v_removed);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Due reminders are returned WITHOUT mutation; the bot acks each one after the
-- DM attempt (send-then-ack: a crash re-sends rather than silently losing one).
CREATE OR REPLACE FUNCTION reminders_due()
RETURNS JSON AS $$
BEGIN
    RETURN COALESCE(
        (SELECT json_agg(json_build_object(
                    'id', r.id,
                    'discord_id', r.discord_id,
                    'content', r.content,
                    'remind_at', r.remind_at,
                    'every_seconds', r.every_seconds
                ) ORDER BY r.remind_at)
         FROM reminders r
         WHERE r.failed = FALSE AND r.remind_at <= NOW()),
        '[]'::json
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Ack one delivery attempt. Repeating reminders advance past every missed
-- occurrence, anchored to the original remind_at (StudyLion's anti-burst,
-- anti-drift rule); one-shots are deleted; failures are flagged, never retried.
CREATE OR REPLACE FUNCTION reminder_ack(p_id BIGINT, p_ok BOOLEAN)
RETURNS JSON AS $$
DECLARE
    v_row reminders%ROWTYPE;
    v_periods BIGINT;
BEGIN
    SELECT * INTO v_row FROM reminders WHERE id = p_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN json_build_object('ok', false, 'error', 'not_found');
    END IF;

    IF NOT p_ok THEN
        UPDATE reminders SET failed = TRUE WHERE id = p_id;
    ELSIF v_row.every_seconds IS NOT NULL THEN
        v_periods := FLOOR(
            EXTRACT(EPOCH FROM (NOW() - v_row.remind_at)) / v_row.every_seconds
        )::BIGINT + 1;
        UPDATE reminders
        SET remind_at = v_row.remind_at + (v_periods * v_row.every_seconds) * INTERVAL '1 second'
        WHERE id = p_id;
    ELSE
        DELETE FROM reminders WHERE id = p_id;
    END IF;

    RETURN json_build_object('ok', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- F. VOICE TIME RPCs
-- =============================================================================

-- Record voice seconds and mint coins for the capped daily delta. The ledger
-- ("already minted today") makes minting idempotent across flushes.
CREATE OR REPLACE FUNCTION add_voice_time(
    p_discord_id TEXT,
    p_channel_id TEXT,
    p_seconds INTEGER,
    p_coins_per_hour INTEGER DEFAULT 50,
    p_daily_cap_seconds INTEGER DEFAULT 57600
)
RETURNS JSON AS $$
DECLARE
    v_day DATE := (NOW() AT TIME ZONE 'Europe/Warsaw')::date;
    v_day_total BIGINT;
    v_total BIGINT;
    v_coins_due BIGINT;
    v_minted BIGINT;
    v_to_mint BIGINT;
BEGIN
    PERFORM _ensure_user_activities(p_discord_id);

    INSERT INTO voice_time_daily (discord_id, day, channel_id, seconds)
    VALUES (p_discord_id, v_day, p_channel_id, GREATEST(p_seconds, 0))
    ON CONFLICT (discord_id, day, channel_id) DO UPDATE
        SET seconds = voice_time_daily.seconds + GREATEST(p_seconds, 0);

    SELECT COALESCE(SUM(seconds), 0) INTO v_day_total
    FROM voice_time_daily WHERE discord_id = p_discord_id AND day = v_day;

    SELECT COALESCE(SUM(seconds), 0) INTO v_total
    FROM voice_time_daily WHERE discord_id = p_discord_id;

    v_coins_due := FLOOR(
        LEAST(v_day_total, p_daily_cap_seconds)::NUMERIC * p_coins_per_hour / 3600
    )::BIGINT;

    SELECT COALESCE(SUM(amount), 0) INTO v_minted
    FROM coin_transactions
    WHERE discord_id = p_discord_id AND reason = 'voice'
      AND (created_at AT TIME ZONE 'Europe/Warsaw')::date = v_day;

    v_to_mint := v_coins_due - v_minted;
    IF v_to_mint > 0 THEN
        INSERT INTO coin_transactions (discord_id, amount, reason, metadata)
        VALUES (p_discord_id, v_to_mint, 'voice',
                jsonb_build_object('channel_id', p_channel_id));

        UPDATE user_activities
        SET coins = coins + v_to_mint, updated_at = NOW()
        WHERE discord_id = p_discord_id;
    ELSE
        v_to_mint := 0;
    END IF;

    RETURN json_build_object(
        'day_seconds', v_day_total,
        'total_seconds', v_total,
        'coins_minted', v_to_mint
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION get_voice_stats(p_discord_id TEXT)
RETURNS JSON AS $$
DECLARE
    v_today DATE := (NOW() AT TIME ZONE 'Europe/Warsaw')::date;
    v_week_start DATE := DATE_TRUNC('week', (NOW() AT TIME ZONE 'Europe/Warsaw'))::date;
    v_month_start DATE := DATE_TRUNC('month', (NOW() AT TIME ZONE 'Europe/Warsaw'))::date;
    v_result JSON;
BEGIN
    SELECT json_build_object(
        'today_seconds',   COALESCE(SUM(seconds) FILTER (WHERE day = v_today), 0),
        'week_seconds',    COALESCE(SUM(seconds) FILTER (WHERE day >= v_week_start), 0),
        'month_seconds',   COALESCE(SUM(seconds) FILTER (WHERE day >= v_month_start), 0),
        'total_seconds',   COALESCE(SUM(seconds), 0)
    ) INTO v_result
    FROM voice_time_daily
    WHERE discord_id = p_discord_id;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- G. POMODORO RPCs
-- =============================================================================

CREATE OR REPLACE FUNCTION pomodoro_upsert(
    p_channel_id TEXT,
    p_focus_seconds INTEGER,
    p_break_seconds INTEGER,
    p_last_started TIMESTAMPTZ,
    p_started_by TEXT
)
RETURNS JSON AS $$
BEGIN
    INSERT INTO pomodoro_timers
        (channel_id, focus_seconds, break_seconds, last_started,
         auto_restart, started_by)
    VALUES (p_channel_id, p_focus_seconds, p_break_seconds, p_last_started,
            FALSE, p_started_by)
    ON CONFLICT (channel_id) DO UPDATE
        SET focus_seconds = EXCLUDED.focus_seconds,
            break_seconds = EXCLUDED.break_seconds,
            last_started = EXCLUDED.last_started,
            auto_restart = FALSE,
            started_by = EXCLUDED.started_by;

    RETURN json_build_object('ok', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Stopped state: last_started NULL. auto_restart marks "stopped because the
-- channel emptied" — the next join restarts the cycle.
CREATE OR REPLACE FUNCTION pomodoro_set_stopped(
    p_channel_id TEXT,
    p_auto_restart BOOLEAN
)
RETURNS JSON AS $$
BEGIN
    UPDATE pomodoro_timers
    SET last_started = NULL, auto_restart = p_auto_restart
    WHERE channel_id = p_channel_id;

    RETURN json_build_object('ok', FOUND);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION pomodoro_delete(p_channel_id TEXT)
RETURNS JSON AS $$
BEGIN
    DELETE FROM pomodoro_timers WHERE channel_id = p_channel_id;
    RETURN json_build_object('ok', FOUND);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION pomodoro_list_all()
RETURNS JSON AS $$
BEGIN
    RETURN COALESCE(
        (SELECT json_agg(json_build_object(
                    'channel_id', t.channel_id,
                    'focus_seconds', t.focus_seconds,
                    'break_seconds', t.break_seconds,
                    'last_started', t.last_started,
                    'auto_restart', t.auto_restart,
                    'started_by', t.started_by
                ))
         FROM pomodoro_timers t),
        '[]'::json
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- H. RANKS RPC
-- =============================================================================

-- Record that a rank threshold's coin reward was granted. newly_awarded=false
-- when the user already reached this (or a higher) threshold before.
CREATE OR REPLACE FUNCTION record_rank_award(p_discord_id TEXT, p_hours INTEGER)
RETURNS JSON AS $$
DECLARE
    v_current INTEGER;
BEGIN
    INSERT INTO user_rank_state (discord_id, awarded_hours)
    VALUES (p_discord_id, 0)
    ON CONFLICT (discord_id) DO NOTHING;

    SELECT awarded_hours INTO v_current
    FROM user_rank_state WHERE discord_id = p_discord_id
    FOR UPDATE;

    IF v_current < p_hours THEN
        UPDATE user_rank_state
        SET awarded_hours = p_hours, updated_at = NOW()
        WHERE discord_id = p_discord_id;
        RETURN json_build_object('newly_awarded', true);
    END IF;

    RETURN json_build_object('newly_awarded', false);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- I. SHOP RPCs
-- =============================================================================

CREATE OR REPLACE FUNCTION shop_list()
RETURNS JSON AS $$
BEGIN
    RETURN COALESCE(
        (SELECT json_agg(json_build_object(
                    'id', s.id,
                    'role_id', s.role_id,
                    'name', s.name,
                    'price', s.price
                ) ORDER BY s.price, s.id)
         FROM shop_items s
         WHERE s.active AND s.deleted_at IS NULL),
        '[]'::json
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION shop_add_item(p_role_id TEXT, p_name TEXT, p_price BIGINT)
RETURNS JSON AS $$
BEGIN
    INSERT INTO shop_items (role_id, name, price)
    VALUES (p_role_id, p_name, p_price)
    ON CONFLICT (role_id) DO UPDATE
        SET name = EXCLUDED.name, price = EXCLUDED.price,
            active = TRUE, deleted_at = NULL;

    RETURN json_build_object('ok', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION shop_remove_item(p_role_id TEXT)
RETURNS JSON AS $$
BEGIN
    UPDATE shop_items SET active = FALSE, deleted_at = NOW()
    WHERE role_id = p_role_id AND deleted_at IS NULL;

    RETURN json_build_object('ok', FOUND);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Debit for a shop item (atomic balance check via adjust_coins). The Discord
-- role juggling happens in the cog after ok=true.
CREATE OR REPLACE FUNCTION shop_buy(p_discord_id TEXT, p_role_id TEXT)
RETURNS JSON AS $$
DECLARE
    v_item shop_items%ROWTYPE;
    v_result JSON;
BEGIN
    SELECT * INTO v_item
    FROM shop_items
    WHERE role_id = p_role_id AND active AND deleted_at IS NULL;
    IF NOT FOUND THEN
        RETURN json_build_object('ok', false, 'error', 'not_found');
    END IF;

    v_result := adjust_coins(
        p_discord_id, -v_item.price, 'shop',
        jsonb_build_object('role_id', p_role_id, 'price', v_item.price)
    );
    IF NOT (v_result ->> 'ok')::boolean THEN
        RETURN json_build_object('ok', false, 'error', 'insufficient',
                                 'balance', (v_result ->> 'balance')::bigint,
                                 'price', v_item.price);
    END IF;

    RETURN json_build_object('ok', true, 'name', v_item.name,
                             'price', v_item.price,
                             'balance', (v_result ->> 'balance')::bigint);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- J. EXTENDED STATS RPC (v3 — supersedes scripts/unified_progress_stats.sql)
-- Adds coins, voice totals, todo counters and GM stats for the progress card
-- and /statystyki.
-- =============================================================================

CREATE OR REPLACE FUNCTION get_user_activity_stats(p_discord_id TEXT)
RETURNS JSON AS $$
DECLARE
    v_result JSON;
BEGIN
    -- streak_* are the monthly counts (reset monthly); total_* are lifetime
    -- grand totals derived from activity_logs (never reset).
    SELECT json_build_object(
        'discord_id', p_discord_id,
        'streak_trening',   COALESCE(ua.streak_trening, 0),
        'streak_medytacja', COALESCE(ua.streak_medytacja, 0),
        'streak_sukces',    COALESCE(ua.streak_sukces, 0),
        'streak_dziennik',  COALESCE(ua.streak_dziennik, 0),
        'last_reset', ua.last_reset,
        'total_trening',   COALESCE(t.total_trening, 0),
        'total_medytacja', COALESCE(t.total_medytacja, 0),
        'total_sukces',    COALESCE(t.total_sukces, 0),
        'total_dziennik',  COALESCE(t.total_dziennik, 0),
        'total_daily_coaching', COALESCE(t.total_daily_coaching, 0),
        'total_deep_work',      COALESCE(t.total_deep_work, 0),
        'deep_work_seconds',    COALESCE(ua.deep_work_seconds, 0),
        'coins',                COALESCE(ua.coins, 0),
        'voice_seconds_total',  COALESCE(v.voice_total, 0),
        'tasks_done_total',     COALESCE(td.done_total, 0),
        'tasks_open',           COALESCE(td.open_total, 0),
        'gm_total',             COALESCE(mcs.total_checkins, 0),
        'gm_momentum',          COALESCE(mcs.current_momentum, 0)
    ) INTO v_result
    FROM (SELECT p_discord_id AS discord_id) base
    LEFT JOIN user_activities ua ON ua.discord_id = base.discord_id
    LEFT JOIN morning_checkin_stats mcs ON mcs.discord_id = base.discord_id
    LEFT JOIN (
        SELECT discord_id,
            COUNT(*) FILTER (WHERE activity_type = 'trening')   AS total_trening,
            COUNT(*) FILTER (WHERE activity_type = 'medytacja') AS total_medytacja,
            COUNT(*) FILTER (WHERE activity_type = 'sukces')    AS total_sukces,
            COUNT(*) FILTER (WHERE activity_type = 'dziennik')  AS total_dziennik,
            COUNT(*) FILTER (WHERE activity_type = 'daily_coaching') AS total_daily_coaching,
            COUNT(*) FILTER (WHERE activity_type = 'deep_work')      AS total_deep_work
        FROM activity_logs
        WHERE discord_id = p_discord_id
        GROUP BY discord_id
    ) t ON t.discord_id = base.discord_id
    LEFT JOIN (
        SELECT discord_id, SUM(seconds) AS voice_total
        FROM voice_time_daily
        WHERE discord_id = p_discord_id
        GROUP BY discord_id
    ) v ON v.discord_id = base.discord_id
    LEFT JOIN (
        SELECT discord_id,
            COUNT(*) FILTER (WHERE completed_at IS NOT NULL) AS done_total,
            COUNT(*) FILTER (WHERE completed_at IS NULL)     AS open_total
        FROM todo_items
        WHERE discord_id = p_discord_id AND deleted_at IS NULL
        GROUP BY discord_id
    ) td ON td.discord_id = base.discord_id;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- K. EXTENDED LEADERBOARD RPC (v3 — supersedes scripts/unified_leaderboard.sql)
-- Adds 'coins' (earned this Warsaw month, transfers-in excluded) and 'voice'
-- (this month's voice seconds; the cog renders seconds as a duration).
-- =============================================================================

CREATE OR REPLACE FUNCTION get_activity_leaderboard(
    p_activity TEXT,
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    rank BIGINT,
    discord_id TEXT,
    streak_count INTEGER,
    user_id UUID
) AS $$
BEGIN
    IF p_activity IN ('daily_coaching', 'deep_work') THEN
        -- Join-based activities: count this month's activity_logs rows.
        RETURN QUERY
        SELECT
            ROW_NUMBER() OVER (ORDER BY c.cnt DESC) AS rank,
            c.discord_id,
            c.cnt::INTEGER AS streak_count,
            c.user_id
        FROM (
            SELECT
                al.discord_id,
                COUNT(*) AS cnt,
                (ARRAY_AGG(al.user_id))[1] AS user_id
            FROM activity_logs al
            WHERE al.activity_type = p_activity
              AND (al.logged_at AT TIME ZONE 'Europe/Warsaw')::date
                  >= DATE_TRUNC('month', (NOW() AT TIME ZONE 'Europe/Warsaw'))::date
            GROUP BY al.discord_id
        ) c
        ORDER BY c.cnt DESC
        LIMIT p_limit;
    ELSIF p_activity = 'coins' THEN
        -- Coins EARNED this Warsaw month (positive ledger rows, transfers-in
        -- excluded so gifting can't game the board).
        RETURN QUERY
        SELECT
            ROW_NUMBER() OVER (ORDER BY c.earned DESC) AS rank,
            c.discord_id,
            c.earned::INTEGER AS streak_count,
            ua.user_id
        FROM (
            SELECT ct.discord_id, SUM(ct.amount) AS earned
            FROM coin_transactions ct
            WHERE ct.amount > 0
              AND ct.reason <> 'transfer_in'
              AND (ct.created_at AT TIME ZONE 'Europe/Warsaw')::date
                  >= DATE_TRUNC('month', (NOW() AT TIME ZONE 'Europe/Warsaw'))::date
            GROUP BY ct.discord_id
        ) c
        LEFT JOIN user_activities ua ON ua.discord_id = c.discord_id
        ORDER BY c.earned DESC
        LIMIT p_limit;
    ELSIF p_activity = 'voice' THEN
        -- This month's tracked voice time in seconds.
        RETURN QUERY
        SELECT
            ROW_NUMBER() OVER (ORDER BY c.secs DESC) AS rank,
            c.discord_id,
            c.secs::INTEGER AS streak_count,
            ua.user_id
        FROM (
            SELECT vtd.discord_id, SUM(vtd.seconds) AS secs
            FROM voice_time_daily vtd
            WHERE vtd.day >= DATE_TRUNC('month', (NOW() AT TIME ZONE 'Europe/Warsaw'))::date
            GROUP BY vtd.discord_id
        ) c
        LEFT JOIN user_activities ua ON ua.discord_id = c.discord_id
        ORDER BY c.secs DESC
        LIMIT p_limit;
    ELSE
        RETURN QUERY EXECUTE format(
            'SELECT
                ROW_NUMBER() OVER (ORDER BY streak_%I DESC) as rank,
                ua.discord_id,
                ua.streak_%I as streak_count,
                ua.user_id
            FROM user_activities ua
            WHERE ua.streak_%I > 0
            ORDER BY ua.streak_%I DESC
            LIMIT $1',
            p_activity, p_activity, p_activity, p_activity
        ) USING p_limit;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- DONE — apply this script, then pull + restart the bot.
-- =============================================================================
