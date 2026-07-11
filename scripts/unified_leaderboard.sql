-- Unified leaderboard: extend get_activity_leaderboard so /leaderboard covers the
-- same categories as the unified progress card. Self-reported activities keep the
-- existing streak_* (monthly) ranking; 'daily_coaching' and 'deep_work' are ranked
-- by this month's join count in activity_logs (Warsaw-local month).
--
-- Apply manually in the Supabase SQL editor, then restart the bot.

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
        -- Join-based activities have no streak_* column in user_activities;
        -- count this month's rows in activity_logs instead.
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
