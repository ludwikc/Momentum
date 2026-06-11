import discord
from config import ACTIVITIES


def build_activity_embed(user, activity_type, result, all_stats):
    """Build the shared "Aktywność" embed.

    Main line shows the monthly count and, when the consecutive-day streak is
    greater than 2, appends "(N z rzędu!)". The per-activity counters below are
    lifetime grand totals (never reset), with a fallback to the monthly streak
    values if the updated Supabase functions have not been applied yet.
    """
    streak_count = result.get("streak_count", 1)
    consecutive = result.get("consecutive_count", 0)

    line = f"🔥 To {streak_count} {activity_type} w tym miesiącu!"
    if consecutive > 2:
        line += f" ({consecutive} z rzędu!)"

    embed = discord.Embed(title="Aktywność", color=0x280586)
    embed.add_field(name="", value=line)

    avatar = user.avatar or user.default_avatar
    embed.set_thumbnail(url=avatar.url)

    if all_stats:
        for name, emoji in ACTIVITIES.items():
            count = all_stats.get(f"total_{name}", all_stats.get(f"streak_{name}", 0))
            if count > 0:
                embed.add_field(
                    name=f"{emoji} {name.capitalize()}: {count}",
                    value="",
                    inline=False,
                )

    return embed
