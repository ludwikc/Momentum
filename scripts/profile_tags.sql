-- =============================================================================
-- PROFILE TAGS (2026-07) — StudyLion "student profile card" port (/profil).
-- Custom self-description tags (max 5 × 30 chars) + get_user_activity_stats v4
-- (v3 from scripts/studylion_port.sql + profile_tags field — this script
-- supersedes that definition; run it AFTER studylion_port.sql).
--
-- Idempotent: safe to run more than once in the Supabase SQL editor.
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_profiles (
    discord_id TEXT PRIMARY KEY,
    tags TEXT[] NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_user_profiles" ON user_profiles;
CREATE POLICY "service_role_all_user_profiles" ON user_profiles
    FOR ALL USING (auth.role() = 'service_role');

-- Set (replace) a user's profile tags. The cog validates too; this is the
-- server-side backstop.
CREATE OR REPLACE FUNCTION profile_set_tags(p_discord_id TEXT, p_tags TEXT[])
RETURNS JSON AS $$
DECLARE
    v_tag TEXT;
BEGIN
    IF COALESCE(array_length(p_tags, 1), 0) > 5 THEN
        RETURN json_build_object('ok', false, 'error', 'too_many');
    END IF;
    FOREACH v_tag IN ARRAY p_tags LOOP
        IF char_length(v_tag) < 1 OR char_length(v_tag) > 30 THEN
            RETURN json_build_object('ok', false, 'error', 'bad_tag');
        END IF;
    END LOOP;

    INSERT INTO user_profiles (discord_id, tags)
    VALUES (p_discord_id, p_tags)
    ON CONFLICT (discord_id) DO UPDATE
        SET tags = EXCLUDED.tags, updated_at = NOW();

    RETURN json_build_object('ok', true, 'tags', to_json(p_tags));
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- get_user_activity_stats v4: v3 (studylion_port.sql) + profile_tags.
-- ============================================================================

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
        'gm_momentum',          COALESCE(mcs.current_momentum, 0),
        'profile_tags',         COALESCE(to_json(up.tags), '[]'::json)
    ) INTO v_result
    FROM (SELECT p_discord_id AS discord_id) base
    LEFT JOIN user_activities ua ON ua.discord_id = base.discord_id
    LEFT JOIN morning_checkin_stats mcs ON mcs.discord_id = base.discord_id
    LEFT JOIN user_profiles up ON up.discord_id = base.discord_id
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
-- DONE — apply after studylion_port.sql, then pull + restart the bot.
-- =============================================================================
