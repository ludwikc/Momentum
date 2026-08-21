"""/statystyki — personal stats card (StudyLion /stats port, embed edition).

Voice time today/week/month/all-time (Warsaw boundaries), coins, todo counts,
the four activities, Daily Coaching, Deep Work and GM — one public embed.
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging

from activity_embed import format_duration_pl
from config import ACTIVITIES, COINS_EMOJI
from db import get_user_activity_stats, get_voice_stats

logger = logging.getLogger("momentum_bot.statystyki")


class Statystyki(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("Statystyki cog initialized")

    @app_commands.command(
        name="statystyki",
        description="Pokaż statystyki (swoje lub innej osoby)",
    )
    @app_commands.describe(uzytkownik="Czyje statystyki (domyślnie Twoje)")
    async def statystyki(
        self,
        interaction: discord.Interaction,
        uzytkownik: discord.Member | None = None,
    ):
        member = uzytkownik or interaction.user
        if member.bot:
            await interaction.response.send_message(
                "Boty nie prowadzą statystyk. 🤖", ephemeral=True
            )
            return
        try:
            stats = get_user_activity_stats(str(member.id)) or {}
            try:
                voice = get_voice_stats(str(member.id)) or {}
            except Exception as e:
                logger.warning(f"get_voice_stats failed for {member.id}: {e}")
                voice = {}

            embed = discord.Embed(
                title=f"📊 Statystyki — {member.display_name}", color=0x280586
            )
            avatar = member.avatar or member.default_avatar
            embed.set_thumbnail(url=avatar.url)

            if voice:
                embed.add_field(
                    name="🎙️ Na głosowych",
                    value=(
                        f"Dziś: **{format_duration_pl(voice.get('today_seconds', 0))}**\n"
                        f"Ten tydzień: **{format_duration_pl(voice.get('week_seconds', 0))}**\n"
                        f"Ten miesiąc: **{format_duration_pl(voice.get('month_seconds', 0))}**\n"
                        f"Łącznie: **{format_duration_pl(voice.get('total_seconds', 0))}**"
                    ),
                    inline=False,
                )

            embed.add_field(
                name=f"{COINS_EMOJI} Monety: {stats.get('coins', 0)}",
                value="",
                inline=False,
            )

            tasks_open = stats.get("tasks_open", 0)
            tasks_done = stats.get("tasks_done_total", 0)
            if tasks_open or tasks_done:
                embed.add_field(
                    name=f"✅ Zadania: {tasks_done} ukończonych • {tasks_open} otwartych",
                    value="",
                    inline=False,
                )

            activity_bits = [
                f"{emoji} {stats.get(f'total_{name}', 0)}"
                for name, emoji in ACTIVITIES.items()
                if stats.get(f"total_{name}", 0) > 0
            ]
            if activity_bits:
                embed.add_field(
                    name="Aktywności: " + " · ".join(activity_bits),
                    value="",
                    inline=False,
                )

            coaching = stats.get("total_daily_coaching", 0)
            if coaching:
                embed.add_field(
                    name=f"🔢 Daily Coaching: {coaching}", value="", inline=False
                )

            dw_seconds = stats.get("deep_work_seconds", 0)
            dw_sessions = stats.get("total_deep_work", 0)
            if dw_seconds or dw_sessions:
                embed.add_field(
                    name=(
                        f"⚓️ Deep Work: {format_duration_pl(dw_seconds)}"
                        f" ({dw_sessions} sesji)"
                    ),
                    value="",
                    inline=False,
                )

            gm_total = stats.get("gm_total", 0)
            gm_momentum = stats.get("gm_momentum", 0)
            if gm_total:
                embed.add_field(
                    name=f"☀️ GM: {gm_total} pobudek (momentum {gm_momentum})",
                    value="",
                    inline=False,
                )

            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"Error in /statystyki: {e}")
            await interaction.response.send_message(
                "Wystąpił błąd podczas pobierania statystyk. Spróbuj ponownie później.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Statystyki(bot))
