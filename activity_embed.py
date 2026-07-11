import discord
from config import ACTIVITIES, COINS_EMOJI


def _plural_pl(n: int, one: str, few: str, many: str) -> str:
    """Polish plural selection (e.g. godzina/godziny/godzin)."""
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many


def format_duration_pl(seconds: int) -> str:
    """Format a duration in seconds as Polish 'X godzin i Y minut'."""
    minutes_total = max(seconds, 0) // 60
    hours = minutes_total // 60
    minutes = minutes_total % 60
    h_word = _plural_pl(hours, "godzina", "godziny", "godzin")
    m_word = _plural_pl(minutes, "minuta", "minuty", "minut")
    if hours > 0 and minutes > 0:
        return f"{hours} {h_word} i {minutes} {m_word}"
    if hours > 0:
        return f"{hours} {h_word}"
    return f"{minutes} {m_word}"


def build_progress_embed(user, headline, all_stats):
    """Build the unified "Aktywność" card: an event-specific headline followed
    by the user's complete lifetime counters — self-reported activities, Daily
    Coaching, and Deep Work (time + sessions). Zero rows are omitted; the Daily
    Coaching / Deep Work rows also stay hidden until the extended
    get_user_activity_stats RPC (scripts/unified_progress_stats.sql) is applied.
    """
    embed = discord.Embed(title="Aktywność", color=0x280586)
    embed.add_field(name="", value=headline, inline=False)

    avatar = user.avatar or user.default_avatar
    embed.set_thumbnail(url=avatar.url)

    stats = all_stats or {}
    for name, emoji in ACTIVITIES.items():
        count = stats.get(f"total_{name}", stats.get(f"streak_{name}", 0))
        if count > 0:
            embed.add_field(
                name=f"{emoji} {name.capitalize()}: {count}",
                value="",
                inline=False,
            )

    coaching_count = stats.get("total_daily_coaching", 0)
    if coaching_count > 0:
        embed.add_field(
            name=f"🔢 Daily Coaching: {coaching_count}",
            value="",
            inline=False,
        )

    dw_sessions = stats.get("total_deep_work", 0)
    dw_seconds = stats.get("deep_work_seconds", 0)
    if dw_sessions > 0 or dw_seconds > 0:
        sessions_text = ""
        if dw_sessions > 0:
            word = _plural_pl(dw_sessions, "sesja", "sesje", "sesji")
            sessions_text = f"{dw_sessions} {word}"
        if dw_seconds > 0 and sessions_text:
            dw_text = f"{format_duration_pl(dw_seconds)} ({sessions_text})"
        elif dw_seconds > 0:
            dw_text = format_duration_pl(dw_seconds)
        else:
            dw_text = sessions_text
        embed.add_field(
            name=f"⚓️ Deep Work: {dw_text}",
            value="",
            inline=False,
        )

    # StudyLion-port rows (need scripts/studylion_port.sql; hidden until the
    # extended get_user_activity_stats returns them — same pattern as above).
    voice_seconds = stats.get("voice_seconds_total", 0)
    if voice_seconds > 0:
        embed.add_field(
            name=f"🎙️ Na głosowych: {format_duration_pl(voice_seconds)}",
            value="",
            inline=False,
        )

    tasks_done = stats.get("tasks_done_total", 0)
    if tasks_done > 0:
        embed.add_field(
            name=f"✅ Zadania: {tasks_done}",
            value="",
            inline=False,
        )

    coins = stats.get("coins", 0)
    if coins > 0:
        embed.add_field(
            name=f"{COINS_EMOJI} Monety: {coins}",
            value="",
            inline=False,
        )

    return embed


def build_activity_embed(user, activity_type, result, all_stats):
    """Progress card for a self-reported activity: headline shows the monthly
    count and, when the consecutive-day streak exceeds 2, "(N z rzędu!)"."""
    streak_count = result.get("streak_count", 1)
    consecutive = result.get("consecutive_count", 0)

    headline = f"🔥 To {streak_count} {activity_type} w tym miesiącu!"
    if consecutive > 2:
        headline += f" ({consecutive} z rzędu!)"

    return build_progress_embed(user, headline, all_stats)
