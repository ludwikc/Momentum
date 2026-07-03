-- Unified progress card: extend get_user_activity_stats with Daily Coaching and
-- Deep Work lifetime counters so every "Aktywność" embed can render the full
-- per-user card (see docs/superpowers/specs/2026-07-03-unified-progress-card-design.md).
--
-- Apply manually in the Supabase SQL editor, then restart the bot.

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
        'deep_work_seconds',    COALESCE(ua.deep_work_seconds, 0)
    ) INTO v_result
    FROM (SELECT p_discord_id AS discord_id) base
    LEFT JOIN user_activities ua ON ua.discord_id = base.discord_id
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
    ) t ON t.discord_id = base.discord_id;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
