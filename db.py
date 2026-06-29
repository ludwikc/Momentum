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


def add_deep_work_time(discord_id: str, seconds: int) -> dict:
    """Add to a user's lifetime Deep Work connection time. Returns {total_seconds}."""
    supabase = get_supabase()
    result = supabase.rpc(
        "add_deep_work_time",
        {"p_discord_id": discord_id, "p_seconds": seconds}
    ).execute()

    return result.data


def get_deep_work_seconds(discord_id: str) -> dict:
    """Get a user's lifetime Deep Work connection time. Returns {total_seconds}."""
    supabase = get_supabase()
    result = supabase.rpc(
        "get_deep_work_seconds",
        {"p_discord_id": discord_id}
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
        List of {id, temat, odpowiedz, kategoria, score}, best first (may be empty).
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
