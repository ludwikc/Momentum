import discord
from discord import app_commands
from discord.ext import commands
import logging
from config import ACTIVITIES as act
from db import upsert_activity, get_user_activity_stats

logger = logging.getLogger("momentum_bot.done")


class done(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("Done cog initialized with Supabase")

    @app_commands.command(name="done", description="Zaloguj aktywność")
    @app_commands.describe(activity="Wybierz aktywność")
    @app_commands.choices(
        activity=[
            app_commands.Choice(name=f"{emoji} {name.capitalize()}", value=name)
            for name, emoji in act.items()
        ]
    )
    async def done_command(
        self, interaction: discord.Interaction, activity: app_commands.Choice[str]
    ):
        activity_type = activity.value
        user_id = str(interaction.user.id)

        try:
            # Call Supabase function - handles upsert and monthly reset
            result = upsert_activity(user_id, activity_type)

            if not result:
                await interaction.response.send_message(
                    "Przepraszam, baza danych jest niedostępna. Spróbuj później.",
                    ephemeral=True,
                )
                return

            # Handle both list and dict responses from Supabase RPC
            if isinstance(result, list) and len(result) > 0:
                result = result[0]

            logger.debug(f"upsert_activity result: {result}")

            # Get streak count - try different possible key names
            new_streak = result.get('new_streak') or result.get('streak_count') or result.get(activity_type) or 1

            # Build response embed
            embed = discord.Embed(title="Aktywność", color=0x280586)
            embed.add_field(
                name="",
                value=f"🔥 To {new_streak} {activity_type} w tym miesiącu!",
            )

            avatar = interaction.user.avatar or interaction.user.default_avatar
            embed.set_thumbnail(url=avatar.url)

            # Show all streaks - handle different response formats
            streaks = result.get("all_streaks", {})
            if isinstance(streaks, dict):
                for name, streak_count in streaks.items():
                    if name in act:
                        embed.add_field(
                            name=f"{act[name]} {name.capitalize()}: {streak_count}",
                            value="",
                            inline=False,
                        )
            else:
                # If all_streaks is not present, show streak for current activity
                embed.add_field(
                    name=f"{act.get(activity_type, '✅')} {activity_type.capitalize()}: {new_streak}",
                    value="",
                    inline=False,
                )

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error in done_command: {e}")
            await interaction.response.send_message(
                "Wystąpił błąd podczas zapisywania aktywności. Spróbuj ponownie później.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(done(bot))
