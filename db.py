"""
Supabase database client for Momentum bot.
Replaces MongoDB (linkdb) with Supabase PostgreSQL.
"""
import os
import logging
from supabase import create_client, Client

logger = logging.getLogger("momentum_bot.db")

# Supabase client singleton
_supabase_client: Client | None = None


def get_supabase() -> Client:
    """Get or create Supabase client singleton."""
    global _supabase_client

    if _supabase_client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")

        if not url or not key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_KEY must be set in environment variables"
            )

        _supabase_client = create_client(url, key)
        logger.info("Connected to Supabase")

    return _supabase_client


# === Activity Functions ===

def upsert_activity(discord_id: str, activity: str, xp_amount: int = 10) -> dict:
    """
    Log an activity for a user. Creates user if not exists.
    Handles monthly reset automatically.

    Args:
        discord_id: Discord user ID as string
        activity: One of 'trening', 'medytacja', 'sukces', 'dziennik'
        xp_amount: XP to award (default 10)

    Returns:
        dict with user's current streaks and activity info
    """
    supabase = get_supabase()
    result = supabase.rpc(
        "upsert_activity",
        {"p_discord_id": discord_id, "p_activity": activity, "p_xp_amount": xp_amount}
    ).execute()

    return result.data


def get_user_activity_stats(discord_id: str) -> dict | None:
    """
    Get all activity stats for a user.

    Returns:
        dict with streaks or None if user not found
    """
    supabase = get_supabase()
    result = supabase.rpc(
        "get_user_activity_stats",
        {"p_discord_id": discord_id}
    ).execute()

    return result.data


def get_activity_leaderboard(activity: str, limit: int = 10) -> list[dict]:
    """
    Get top users for a specific activity.

    Args:
        activity: One of 'trening', 'medytacja', 'sukces', 'dziennik'
        limit: Number of results (default 10)

    Returns:
        List of {rank, discord_id, streak_count, user_id}
    """
    supabase = get_supabase()
    result = supabase.rpc(
        "get_activity_leaderboard",
        {"p_activity": activity, "p_limit": limit}
    ).execute()

    return result.data or []


# === Session Trackers (Daily Coaching / Deep Work) ===

def log_capped_join(discord_id: str, activity: str, max_per_day: int) -> dict:
    """
    Log a join-based activity (e.g. 'daily_coaching', 'deep_work') up to a
    per-day cap. Counts use Warsaw-local days/months.

    Returns:
        dict with {logged: bool, monthly_count, total_count} when logged,
        or {logged: false} when the daily cap is already reached.
    """
    supabase = get_supabase()
    result = supabase.rpc(
        "log_capped_join",
        {"p_discord_id": discord_id, "p_activity": activity, "p_max_per_day": max_per_day}
    ).execute()

    return result.data


def log_capped_month(discord_id: str, activity: str, max_per_month: int) -> dict:
    """
    Log an activity up to a per-MONTH cap (Warsaw-local month). Used for the
    monthly coaching limit. Counts/inserts via the log_capped_month RPC
    (scripts/coaching_limit.sql).

    Returns:
        dict with {logged: bool, monthly_count: int} — logged is False (and no
        row written) once the cap is reached.
    """
    supabase = get_supabase()
    result = supabase.rpc(
        "log_capped_month",
        {"p_discord_id": discord_id, "p_activity": activity, "p_max_per_month": max_per_month},
    ).execute()

    return result.data


def add_deep_work_time(discord_id: str, seconds: int) -> dict:
    """Add to a user's lifetime Deep Work connection time. Returns {total_seconds}."""
    supabase = get_supabase()
    result = supabase.rpc(
        "add_deep_work_time",
        {"p_discord_id": discord_id, "p_seconds": seconds}
    ).execute()

    return result.data


# === Wake-up / Morning Check-in Functions ===

def check_morning_checkin(discord_id: str) -> dict:
    """
    Record a morning check-in for a user.
    Handles early bird detection (4-6 AM) and momentum tracking.

    Args:
        discord_id: Discord user ID as string

    Returns:
        dict with check-in result including:
        - success: bool
        - is_early_bird: bool
        - current_momentum: int
        - total_checkins: int
        - message: str (if already checked in today)
    """
    supabase = get_supabase()
    result = supabase.rpc(
        "check_morning_checkin",
        {"p_discord_id": discord_id}
    ).execute()

    return result.data


def get_wakeup_leaderboard(leaderboard_type: str = "momentum", limit: int = 10) -> list[dict]:
    """
    Get wake-up leaderboard.

    Args:
        leaderboard_type: 'total', 'momentum', or 'early_bird'
        limit: Number of results (default 10)

    Returns:
        List of {rank, discord_id, count, user_id}
    """
    supabase = get_supabase()
    result = supabase.rpc(
        "get_wakeup_leaderboard",
        {"p_type": leaderboard_type, "p_limit": limit}
    ).execute()

    return result.data or []


# === User Linking ===

def link_discord_to_portal_user(discord_id: str, user_id: str) -> bool:
    """
    Link a Discord user to their Portal account.
    Called when user logs into Portal via Discord OAuth.

    Args:
        discord_id: Discord user ID
        user_id: Portal user UUID

    Returns:
        True if successful
    """
    supabase = get_supabase()
    result = supabase.rpc(
        "link_discord_to_portal_user",
        {"p_discord_id": discord_id, "p_user_id": user_id}
    ).execute()

    return True


# === Knowledge Base (hybrid pgvector + FTS search) ===

def search_knowledge(
    query_text: str,
    query_embedding,
    match_count: int = 3,
    kategoria: str | None = None,
) -> list[dict]:
    """
    Hybrid search over the knowledge_base table (semantic + lexical, RRF).

    Calls the match_knowledge RPC defined in scripts/knowledge_schema.sql.

    Args:
        query_text: the question/topic in natural language (used for the FTS leg)
        query_embedding: the query embedding — pass as a pgvector-literal string
            like "[0.1,0.2,...]" (see cogs/przywolanie.py); a plain list also works
            but the string form is the most reliable through PostgREST
        match_count: how many top matches to return
        kategoria: optional category filter

    Returns:
        List of {id, temat, tresc, kategoria, score}, best first (may be empty).
    """
    supabase = get_supabase()
    result = supabase.rpc(
        "match_knowledge",
        {
            "query_text": query_text,
            "query_embedding": query_embedding,
            "match_count": match_count,
            "filter_kategoria": kategoria,
        },
    ).execute()

    return result.data or []


# === Economy (StudyLion port — scripts/studylion_port.sql) ===

def adjust_coins(discord_id: str, amount: int, reason: str, metadata: dict | None = None) -> dict:
    """Change a user's coin balance through the ledger. Floors at 0:
    returns {ok: False, error: 'insufficient', balance} instead of going negative."""
    supabase = get_supabase()
    result = supabase.rpc(
        "adjust_coins",
        {"p_discord_id": discord_id, "p_amount": amount,
         "p_reason": reason, "p_metadata": metadata},
    ).execute()
    return result.data


def award_coins_safe(
    discord_id: str, amount: int, reason: str, metadata: dict | None = None
) -> dict | None:
    """Best-effort coin award for hooks in non-economy flows (/done, GM):
    never raises — the host flow must not break when the economy is down
    (e.g. scripts/studylion_port.sql not applied yet)."""
    try:
        return adjust_coins(discord_id, amount, reason, metadata)
    except Exception as e:
        logger.warning(f"Coin award failed ({reason}) for {discord_id}: {e}")
        return None


def get_coin_summary(discord_id: str) -> dict:
    """{balance, earned_month, earned_total} (earned = positive, transfers-in excluded)."""
    supabase = get_supabase()
    result = supabase.rpc("get_coin_summary", {"p_discord_id": discord_id}).execute()
    return result.data


def transfer_coins(from_id: str, to_id: str, amount: int) -> dict:
    """Atomic member→member coin transfer. {ok, from_balance, to_balance} or {ok: False, error}."""
    supabase = get_supabase()
    result = supabase.rpc(
        "transfer_coins",
        {"p_from": from_id, "p_to": to_id, "p_amount": amount},
    ).execute()
    return result.data


# === Todo list (StudyLion port) ===

def todo_add(discord_id: str, items: list[str], max_open: int = 100) -> dict:
    supabase = get_supabase()
    result = supabase.rpc(
        "todo_add",
        {"p_discord_id": discord_id, "p_items": items, "p_max_open": max_open},
    ).execute()
    return result.data


def todo_list(discord_id: str) -> list[dict]:
    """Live (non-deleted) tasks ordered by id: [{id, content, completed_at, created_at}]."""
    supabase = get_supabase()
    result = supabase.rpc("todo_list", {"p_discord_id": discord_id}).execute()
    return result.data or []


def todo_set_done(
    discord_id: str, ids: list[int], done: bool,
    reward_coins: int = 50, reward_limit_24h: int = 10,
) -> dict:
    """Tick/untick tasks; ticking rewards unrewarded ones up to the rolling-24h
    limit inside the same transaction. {ok, changed, rewarded, coins_minted, balance}."""
    supabase = get_supabase()
    result = supabase.rpc(
        "todo_set_done",
        {"p_discord_id": discord_id, "p_ids": ids, "p_done": done,
         "p_reward_coins": reward_coins, "p_reward_limit_24h": reward_limit_24h},
    ).execute()
    return result.data


def todo_remove(discord_id: str, ids: list[int]) -> dict:
    supabase = get_supabase()
    result = supabase.rpc(
        "todo_remove", {"p_discord_id": discord_id, "p_ids": ids}
    ).execute()
    return result.data


def todo_edit(discord_id: str, item_id: int, content: str) -> dict:
    supabase = get_supabase()
    result = supabase.rpc(
        "todo_edit",
        {"p_discord_id": discord_id, "p_id": item_id, "p_content": content},
    ).execute()
    return result.data


# === Reminders (StudyLion port) ===

def reminder_add(
    discord_id: str, content: str, remind_at_iso: str,
    every_seconds: int | None = None,
    max_per_user: int = 25, min_every_seconds: int = 600,
) -> dict:
    """{ok, id, count} or {ok: False, error: 'past'|'min_interval'|'limit'}."""
    supabase = get_supabase()
    result = supabase.rpc(
        "reminder_add",
        {"p_discord_id": discord_id, "p_content": content,
         "p_remind_at": remind_at_iso, "p_every_seconds": every_seconds,
         "p_max_per_user": max_per_user, "p_min_every_seconds": min_every_seconds},
    ).execute()
    return result.data


def reminder_list(discord_id: str) -> list[dict]:
    supabase = get_supabase()
    result = supabase.rpc("reminder_list", {"p_discord_id": discord_id}).execute()
    return result.data or []


def reminder_cancel(discord_id: str, ids: list[int]) -> dict:
    supabase = get_supabase()
    result = supabase.rpc(
        "reminder_cancel", {"p_discord_id": discord_id, "p_ids": ids}
    ).execute()
    return result.data


def reminders_due() -> list[dict]:
    """Due, unfailed reminders (no mutation — ack each after the DM attempt)."""
    supabase = get_supabase()
    result = supabase.rpc("reminders_due", {}).execute()
    return result.data or []


def reminder_ack(reminder_id: int, ok: bool) -> dict:
    """After a delivery attempt: advance repeating / delete one-shot / flag failed."""
    supabase = get_supabase()
    result = supabase.rpc(
        "reminder_ack", {"p_id": reminder_id, "p_ok": ok}
    ).execute()
    return result.data


# === Voice time tracking (StudyLion port) ===

def add_voice_time(
    discord_id: str, channel_id: str, seconds: int,
    coins_per_hour: int = 50, daily_cap_seconds: int = 57600,
) -> dict:
    """Record voice seconds (Warsaw-day aggregate) and mint capped coins.
    Returns {day_seconds, total_seconds, coins_minted}."""
    supabase = get_supabase()
    result = supabase.rpc(
        "add_voice_time",
        {"p_discord_id": discord_id, "p_channel_id": channel_id,
         "p_seconds": seconds, "p_coins_per_hour": coins_per_hour,
         "p_daily_cap_seconds": daily_cap_seconds},
    ).execute()
    return result.data


def get_voice_stats(discord_id: str) -> dict:
    """{today_seconds, week_seconds, month_seconds, total_seconds} (Warsaw boundaries)."""
    supabase = get_supabase()
    result = supabase.rpc("get_voice_stats", {"p_discord_id": discord_id}).execute()
    return result.data


# === Pomodoro timers (StudyLion port) ===

def pomodoro_upsert(
    channel_id: str, focus_seconds: int, break_seconds: int,
    last_started_iso: str | None, started_by: str,
) -> dict:
    supabase = get_supabase()
    result = supabase.rpc(
        "pomodoro_upsert",
        {"p_channel_id": channel_id, "p_focus_seconds": focus_seconds,
         "p_break_seconds": break_seconds, "p_last_started": last_started_iso,
         "p_started_by": started_by},
    ).execute()
    return result.data


def pomodoro_set_stopped(channel_id: str, auto_restart: bool) -> dict:
    supabase = get_supabase()
    result = supabase.rpc(
        "pomodoro_set_stopped",
        {"p_channel_id": channel_id, "p_auto_restart": auto_restart},
    ).execute()
    return result.data


def pomodoro_delete(channel_id: str) -> dict:
    supabase = get_supabase()
    result = supabase.rpc("pomodoro_delete", {"p_channel_id": channel_id}).execute()
    return result.data


def pomodoro_list_all() -> list[dict]:
    supabase = get_supabase()
    result = supabase.rpc("pomodoro_list_all", {}).execute()
    return result.data or []


# === Ranks (StudyLion port) ===

def record_rank_award(discord_id: str, hours: int) -> dict:
    """{newly_awarded: bool} — True exactly once per threshold per user."""
    supabase = get_supabase()
    result = supabase.rpc(
        "record_rank_award", {"p_discord_id": discord_id, "p_hours": hours}
    ).execute()
    return result.data


# === Shop (StudyLion port) ===

def shop_list() -> list[dict]:
    supabase = get_supabase()
    result = supabase.rpc("shop_list", {}).execute()
    return result.data or []


def shop_add_item(role_id: str, name: str, price: int) -> dict:
    supabase = get_supabase()
    result = supabase.rpc(
        "shop_add_item", {"p_role_id": role_id, "p_name": name, "p_price": price}
    ).execute()
    return result.data


def shop_remove_item(role_id: str) -> dict:
    supabase = get_supabase()
    result = supabase.rpc("shop_remove_item", {"p_role_id": role_id}).execute()
    return result.data


def shop_buy(discord_id: str, role_id: str) -> dict:
    """Atomic debit for a shop item. {ok, name, price, balance} or {ok: False, error}."""
    supabase = get_supabase()
    result = supabase.rpc(
        "shop_buy", {"p_discord_id": discord_id, "p_role_id": role_id}
    ).execute()
    return result.data
