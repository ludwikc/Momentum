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

            # upsert_activity returns: {success, activity, streak_count, xp_awarded, discord_id, is_linked}
            streak_count = result.get('streak_count', 1)

            # Build response embed
            embed = discord.Embed(title="Aktywność", color=0x280586)
            embed.add_field(
                name="",
                value=f"🔥 To {streak_count} {activity_type} w tym miesiącu!",
            )

            avatar = interaction.user.avatar or interaction.user.default_avatar
            embed.set_thumbnail(url=avatar.url)

            # Get all user streaks from separate function
            # Returns: {discord_id, streak_trening, streak_medytacja, streak_sukces, streak_dziennik, last_reset}
            all_stats = get_user_activity_stats(user_id)
            if all_stats:
                for name, emoji in act.items():
                    streak_key = f"streak_{name}"
                    count = all_stats.get(streak_key, 0)
                    if count > 0:
                        embed.add_field(
                            name=f"{emoji} {name.capitalize()}: {count}",
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
