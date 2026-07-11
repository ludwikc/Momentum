import discord
from discord import app_commands
from discord.ext import commands
import logging
from config import ACTIVITIES as act
from config import DONE_REWARD_COINS
from db import award_activity_coins_safe, upsert_activity, get_user_activity_stats
from activity_embed import build_activity_embed

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

            # StudyLion-port economy hook: coin bonus once per activity per
            # Warsaw day (before fetching stats so the card shows the fresh
            # balance). Streaks stay uncapped — only the coins are gated.
            award_activity_coins_safe(user_id, activity_type, DONE_REWARD_COINS)

            # Build response embed (monthly count + consecutive-day streak +
            # lifetime grand totals)
            all_stats = get_user_activity_stats(user_id)
            embed = build_activity_embed(
                interaction.user, activity_type, result, all_stats
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
