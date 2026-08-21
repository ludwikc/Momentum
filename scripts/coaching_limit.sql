-- Miesięczny limit coachingu Momentum (per użytkownik, trwały).
--
-- Uruchom RĘCZNIE raz w panelu Supabase: SQL editor → wklej całość → Run.
-- Analog istniejącego log_capped_join, ale cap jest MIESIĘCZNY, nie dzienny.
-- Liczy wpisy z bieżącego miesiąca kalendarzowego (czas warszawski) w tabeli
-- activity_logs dla activity_type = 'coaching'. Gdy pod limitem — dopisuje wpis
-- (xp = 0, żeby nie ruszać XP/leaderboardów) i zwraca logged=true; powyżej —
-- logged=false bez wpisu. Reset jest automatyczny wraz ze zmianą miesiąca.

create or replace function log_capped_month(
    p_discord_id   text,
    p_activity     text,
    p_max_per_month integer
)
returns json as $$
declare
    v_month_start date := date_trunc('month', (now() at time zone 'Europe/Warsaw'))::date;
    v_monthly_count integer;
    v_portal_user_id uuid;
begin
    select count(*) into v_monthly_count
    from activity_logs
    where discord_id = p_discord_id
      and activity_type = p_activity
      and (logged_at at time zone 'Europe/Warsaw')::date >= v_month_start;

    if v_monthly_count >= p_max_per_month then
        return json_build_object('logged', false, 'monthly_count', v_monthly_count);
    end if;

    select id into v_portal_user_id from users where discord_id = p_discord_id;

    insert into activity_logs (discord_id, user_id, activity_type, xp_awarded)
    values (p_discord_id, v_portal_user_id, p_activity, 0);

    return json_build_object('logged', true, 'monthly_count', v_monthly_count + 1);
end;
$$ language plpgsql security definer;
