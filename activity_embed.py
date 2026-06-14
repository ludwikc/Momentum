import discord
from config import COUNTERS


def _plural_pl(n: int, one: str, few: str, many: str) -> str:
    """Polish plural selection (e.g. godzina/godziny/godzin)."""
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many


def format_duration_pl(seconds: int) -> str:
    """Format a duration in seconds as Polish 'X godzin i Y minut'."""
    minutes_total = max(int(seconds), 0) // 60
    hours = minutes_total // 60
    minutes = minutes_total % 60
    h_word = _plural_pl(hours, "godzina", "godziny", "godzin")
    m_word = _plural_pl(minutes, "minuta", "minuty", "minut")
    if hours > 0 and minutes > 0:
        return f"{hours} {h_word} i {minutes} {m_word}"
    if hours > 0:
        return f"{hours} {h_word}"
    return f"{minutes} {m_word}"


def build_activity_embed(user, activity_type, result, all_stats):
    """Build the shared "Aktywność" embed.

    Main line shows the monthly count and, when the consecutive-day streak is
    greater than 2, appends "(N z rzędu!)". The per-activity counters below are
    lifetime grand totals (never reset): a join count for most activities, and
    accumulated connection time for Deep Work. Falls back to the monthly streak
    values if the updated Supabase functions have not been applied yet.
    """
    streak_count = result.get("streak_count", result.get("monthly_count", 1))
    consecutive = result.get("consecutive_count", 0)

    line = f"🔥 To {streak_count} {activity_type} w tym miesiącu!"
    if consecutive > 2:
        line += f" ({consecutive} z rzędu!)"

    embed = discord.Embed(title="Aktywność", color=0x280586)
    embed.add_field(name="", value=line)

    avatar = user.avatar or user.default_avatar
    embed.set_thumbnail(url=avatar.url)

    if all_stats:
        for name, (emoji, label) in COUNTERS.items():
            if name == "deep_work":
                seconds = all_stats.get("total_deep_work_seconds", 0) or 0
                if seconds > 0:
                    embed.add_field(
                        name=f"{emoji} {label}: {format_duration_pl(seconds)}",
                        value="",
                        inline=False,
                    )
                continue

            count = all_stats.get(f"total_{name}", all_stats.get(f"streak_{name}", 0)) or 0
            if count > 0:
                embed.add_field(
                    name=f"{emoji} {label}: {count}",
                    value="",
                    inline=False,
                )

    return embed
