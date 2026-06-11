-- =============================================================================
-- MOMENTUM BOT - COMPLETE SUPABASE SCHEMA
-- =============================================================================
-- Run this entire script in Supabase SQL Editor
-- =============================================================================

-- =============================================================================
-- 1. TABLE: user_activities
-- Stores activity streaks (trening, medytacja, sukces, dziennik)
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_activities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity (discord_id required, user_id optional for Portal linking)
    discord_id TEXT NOT NULL UNIQUE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,

    -- Activity streak counters (reset monthly)
    streak_trening INTEGER NOT NULL DEFAULT 0,
    streak_medytacja INTEGER NOT NULL DEFAULT 0,
    streak_sukces INTEGER NOT NULL DEFAULT 0,
    streak_dziennik INTEGER NOT NULL DEFAULT 0,

    -- Monthly reset tracking
    last_reset DATE NOT NULL DEFAULT CURRENT_DATE,

    -- Audit timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_user_activities_discord_id ON user_activities(discord_id);
CREATE INDEX IF NOT EXISTS idx_user_activities_user_id ON user_activities(user_id);

-- =============================================================================
-- 2. TABLE: activity_logs
-- Detailed log of each activity (for history/analytics)
-- =============================================================================

CREATE TABLE IF NOT EXISTS activity_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    discord_id TEXT NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    activity_type TEXT NOT NULL CHECK (
        activity_type IN ('trening', 'medytacja', 'sukces', 'dziennik', 'gm')
    ),
    xp_awarded INTEGER NOT NULL DEFAULT 10,
    logged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_activity_logs_discord_id ON activity_logs(discord_id);
CREATE INDEX IF NOT EXISTS idx_activity_logs_activity_type ON activity_logs(activity_type);
CREATE INDEX IF NOT EXISTS idx_activity_logs_logged_at ON activity_logs(logged_at);

-- =============================================================================
-- 3. TABLE: morning_checkins (if not exists)
-- =============================================================================

CREATE TABLE IF NOT EXISTS morning_checkins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    discord_id TEXT NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    checked_in_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checkin_date DATE NOT NULL DEFAULT CURRENT_DATE,
    is_early_bird BOOLEAN NOT NULL DEFAULT FALSE,

    CONSTRAINT unique_daily_checkin UNIQUE (discord_id, checkin_date)
);

CREATE INDEX IF NOT EXISTS idx_morning_checkins_discord_id ON morning_checkins(discord_id);

-- =============================================================================
-- 4. TABLE: morning_checkin_stats
-- =============================================================================

CREATE TABLE IF NOT EXISTS morning_checkin_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    discord_id TEXT NOT NULL UNIQUE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    total_checkins INTEGER NOT NULL DEFAULT 0,
    total_early_checkins INTEGER NOT NULL DEFAULT 0,
    current_momentum INTEGER NOT NULL DEFAULT 0,
    longest_momentum INTEGER NOT NULL DEFAULT 0,
    last_checkin_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_morning_checkin_stats_discord_id ON morning_checkin_stats(discord_id);

-- =============================================================================
-- 5. FUNCTION: upsert_activity
-- Main function for logging activities with monthly reset
-- =============================================================================

CREATE OR REPLACE FUNCTION upsert_activity(
    p_discord_id TEXT,
    p_activity TEXT,
    p_xp_amount INTEGER DEFAULT 10
)
RETURNS JSON AS $$
DECLARE
    v_current_month DATE;
    v_user_record user_activities%ROWTYPE;
    v_streak_count INTEGER;
    v_total_count INTEGER;
    v_consecutive_count INTEGER;
    v_portal_user_id UUID;
BEGIN
    v_current_month := DATE_TRUNC('month', CURRENT_DATE)::DATE;

    -- Try to find linked Portal user
    SELECT id INTO v_portal_user_id
    FROM users
    WHERE discord_id = p_discord_id;

    -- Get or create user_activities record
    SELECT * INTO v_user_record
    FROM user_activities
    WHERE discord_id = p_discord_id;

    IF NOT FOUND THEN
        -- Create new record
        INSERT INTO user_activities (discord_id, user_id, last_reset)
        VALUES (p_discord_id, v_portal_user_id, v_current_month)
        RETURNING * INTO v_user_record;
    ELSE
        -- Check if we need monthly reset
        IF v_user_record.last_reset < v_current_month THEN
            UPDATE user_activities
            SET streak_trening = 0,
                streak_medytacja = 0,
                streak_sukces = 0,
                streak_dziennik = 0,
                last_reset = v_current_month,
                updated_at = NOW()
            WHERE discord_id = p_discord_id
            RETURNING * INTO v_user_record;
        END IF;
    END IF;

    -- Increment the appropriate streak
    EXECUTE format(
        'UPDATE user_activities SET streak_%I = streak_%I + 1, updated_at = NOW() WHERE discord_id = $1 RETURNING streak_%I',
        p_activity, p_activity, p_activity
    ) INTO v_streak_count USING p_discord_id;

    -- Log the activity
    INSERT INTO activity_logs (discord_id, user_id, activity_type, xp_awarded)
    VALUES (p_discord_id, v_portal_user_id, p_activity, p_xp_amount);

    -- Lifetime grand total for this activity (never resets; derived from activity_logs)
    SELECT COUNT(*) INTO v_total_count
    FROM activity_logs
    WHERE discord_id = p_discord_id AND activity_type = p_activity;

    -- Consecutive-day streak ending today (distinct Warsaw-local days; gaps-and-islands)
    WITH days AS (
        SELECT DISTINCT (logged_at AT TIME ZONE 'Europe/Warsaw')::date AS d
        FROM activity_logs
        WHERE discord_id = p_discord_id AND activity_type = p_activity
    ),
    islands AS (
        SELECT d, d - (ROW_NUMBER() OVER (ORDER BY d) * INTERVAL '1 day') AS grp
        FROM days
    )
    SELECT COUNT(*) INTO v_consecutive_count
    FROM islands
    WHERE grp = (SELECT grp FROM islands ORDER BY d DESC LIMIT 1);

    -- Award XP if user is linked to Portal
    IF v_portal_user_id IS NOT NULL THEN
        INSERT INTO xp_events (user_id, source, xp, metadata)
        VALUES (
            v_portal_user_id,
            'activity_' || p_activity,
            p_xp_amount,
            jsonb_build_object('discord_id', p_discord_id, 'activity', p_activity)
        );
    END IF;

    -- Return result
    RETURN json_build_object(
        'success', true,
        'activity', p_activity,
        'streak_count', v_streak_count,
        'consecutive_count', v_consecutive_count,
        'total_count', v_total_count,
        'xp_awarded', p_xp_amount,
        'discord_id', p_discord_id,
        'is_linked', v_portal_user_id IS NOT NULL
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- 6. FUNCTION: get_user_activity_stats
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
        'total_dziennik',  COALESCE(t.total_dziennik, 0)
    ) INTO v_result
    FROM (SELECT p_discord_id AS discord_id) base
    LEFT JOIN user_activities ua ON ua.discord_id = base.discord_id
    LEFT JOIN (
        SELECT discord_id,
            COUNT(*) FILTER (WHERE activity_type = 'trening')   AS total_trening,
            COUNT(*) FILTER (WHERE activity_type = 'medytacja') AS total_medytacja,
            COUNT(*) FILTER (WHERE activity_type = 'sukces')    AS total_sukces,
            COUNT(*) FILTER (WHERE activity_type = 'dziennik')  AS total_dziennik
        FROM activity_logs
        WHERE discord_id = p_discord_id
        GROUP BY discord_id
    ) t ON t.discord_id = base.discord_id;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- 7. FUNCTION: get_activity_leaderboard
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
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- 8. FUNCTION: check_morning_checkin
-- =============================================================================

CREATE OR REPLACE FUNCTION check_morning_checkin(p_discord_id TEXT)
RETURNS JSON AS $$
DECLARE
    v_today DATE := CURRENT_DATE;
    v_now TIME := CURRENT_TIME;
    v_is_early_bird BOOLEAN;
    v_already_checked BOOLEAN;
    v_stats morning_checkin_stats%ROWTYPE;
    v_portal_user_id UUID;
    v_new_momentum INTEGER;
BEGIN
    -- Check if already checked in today
    SELECT EXISTS(
        SELECT 1 FROM morning_checkins
        WHERE discord_id = p_discord_id
        AND checkin_date = v_today
    ) INTO v_already_checked;

    IF v_already_checked THEN
        RETURN json_build_object(
            'success', false,
            'message', 'Już się dziś zameldowałeś!',
            'already_checked_in', true
        );
    END IF;

    -- Early bird check (4:00 - 6:55 AM)
    v_is_early_bird := v_now >= '04:00:00' AND v_now < '06:55:00';

    -- Find linked Portal user
    SELECT id INTO v_portal_user_id
    FROM users
    WHERE discord_id = p_discord_id;

    -- Insert check-in record
    INSERT INTO morning_checkins (discord_id, user_id, checkin_date, is_early_bird)
    VALUES (p_discord_id, v_portal_user_id, v_today, v_is_early_bird);

    -- Get or create stats
    SELECT * INTO v_stats
    FROM morning_checkin_stats
    WHERE discord_id = p_discord_id;

    IF NOT FOUND THEN
        INSERT INTO morning_checkin_stats (
            discord_id, user_id, total_checkins, total_early_checkins,
            current_momentum, longest_momentum, last_checkin_date
        ) VALUES (
            p_discord_id, v_portal_user_id, 1,
            CASE WHEN v_is_early_bird THEN 1 ELSE 0 END,
            CASE WHEN v_is_early_bird THEN 1 ELSE 0 END,
            CASE WHEN v_is_early_bird THEN 1 ELSE 0 END,
            v_today
        )
        RETURNING * INTO v_stats;
    ELSE
        -- Calculate new momentum
        IF v_is_early_bird AND v_stats.last_checkin_date = v_today - 1 THEN
            v_new_momentum := v_stats.current_momentum + 1;
        ELSIF v_is_early_bird THEN
            v_new_momentum := 1;
        ELSE
            v_new_momentum := 0;
        END IF;

        UPDATE morning_checkin_stats
        SET total_checkins = total_checkins + 1,
            total_early_checkins = total_early_checkins + CASE WHEN v_is_early_bird THEN 1 ELSE 0 END,
            current_momentum = v_new_momentum,
            longest_momentum = GREATEST(longest_momentum, v_new_momentum),
            last_checkin_date = v_today,
            updated_at = NOW()
        WHERE discord_id = p_discord_id
        RETURNING * INTO v_stats;
    END IF;

    -- Log activity
    INSERT INTO activity_logs (discord_id, user_id, activity_type, xp_awarded)
    VALUES (p_discord_id, v_portal_user_id, 'gm', CASE WHEN v_is_early_bird THEN 15 ELSE 10 END);

    RETURN json_build_object(
        'success', true,
        'is_early_bird', v_is_early_bird,
        'current_momentum', v_stats.current_momentum,
        'longest_momentum', v_stats.longest_momentum,
        'total_checkins', v_stats.total_checkins,
        'total_early_checkins', v_stats.total_early_checkins
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- 9. FUNCTION: get_wakeup_leaderboard
-- =============================================================================

CREATE OR REPLACE FUNCTION get_wakeup_leaderboard(
    p_type TEXT DEFAULT 'momentum',
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    rank BIGINT,
    discord_id TEXT,
    count INTEGER,
    user_id UUID
) AS $$
BEGIN
    IF p_type = 'momentum' THEN
        RETURN QUERY
        SELECT
            ROW_NUMBER() OVER (ORDER BY current_momentum DESC) as rank,
            mcs.discord_id,
            mcs.current_momentum as count,
            mcs.user_id
        FROM morning_checkin_stats mcs
        WHERE mcs.current_momentum > 0
        ORDER BY mcs.current_momentum DESC
        LIMIT p_limit;
    ELSIF p_type = 'early_bird' THEN
        RETURN QUERY
        SELECT
            ROW_NUMBER() OVER (ORDER BY total_early_checkins DESC) as rank,
            mcs.discord_id,
            mcs.total_early_checkins as count,
            mcs.user_id
        FROM morning_checkin_stats mcs
        WHERE mcs.total_early_checkins > 0
        ORDER BY mcs.total_early_checkins DESC
        LIMIT p_limit;
    ELSE -- 'total'
        RETURN QUERY
        SELECT
            ROW_NUMBER() OVER (ORDER BY total_checkins DESC) as rank,
            mcs.discord_id,
            mcs.total_checkins as count,
            mcs.user_id
        FROM morning_checkin_stats mcs
        WHERE mcs.total_checkins > 0
        ORDER BY mcs.total_checkins DESC
        LIMIT p_limit;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- 10. RLS POLICIES (Row Level Security)
-- =============================================================================

ALTER TABLE user_activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE morning_checkins ENABLE ROW LEVEL SECURITY;
ALTER TABLE morning_checkin_stats ENABLE ROW LEVEL SECURITY;

-- Service role has full access (for bot)
CREATE POLICY "service_role_all_user_activities" ON user_activities
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_role_all_activity_logs" ON activity_logs
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_role_all_morning_checkins" ON morning_checkins
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_role_all_morning_checkin_stats" ON morning_checkin_stats
    FOR ALL USING (auth.role() = 'service_role');

-- =============================================================================
-- DONE! Your Momentum bot is ready to use.
-- =============================================================================
