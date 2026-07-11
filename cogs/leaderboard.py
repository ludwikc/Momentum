import discord
from discord.ext import commands
from discord import app_commands
from discord import Embed
import logging
from db import get_activity_leaderboard

logger = logging.getLogger("momentum_bot.leaderboard")

# Same categories as the unified progress card: activity value -> (emoji, label).
# The two join-based ones need get_activity_leaderboard from
# scripts/unified_leaderboard.sql applied in Supabase.
CATEGORIES = {
    "trening": ("💪", "Trening"),
    "medytacja": ("🧘", "Medytacja"),
    "sukces": ("💎", "Sukces"),
    "dziennik": ("📝", "Dziennik"),
    "daily_coaching": ("🔢", "Daily Coaching"),
    "deep_work": ("⚓️", "Deep Work"),
}


class leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("Leaderboard cog initialized with Supabase")

    @app_commands.command(
        name="leaderboard",
        description="Pokaż leaderboard dla wybranej aktywności (ten miesiąc)",
    )
    @app_commands.describe(activity="Wybierz aktywność")
    @app_commands.choices(
        activity=[
            app_commands.Choice(name=f"{emoji} {label}", value=name)
            for name, (emoji, label) in CATEGORIES.items()
        ]
    )
    async def leaderboard_command(
        self, interaction: discord.Interaction, activity: app_commands.Choice[str]
    ):
        activity_type = activity.value

        if activity_type not in CATEGORIES:
            await interaction.response.send_message(
                f'Niepoprawna aktywność. Dostępne aktywności: {", ".join(CATEGORIES)}',
                ephemeral=True,
            )
            return

        try:
            # Get leaderboard from Supabase
            entries = get_activity_leaderboard(activity_type, 10)

            emoji, label = CATEGORIES[activity_type]

            embed = Embed(
                title=f"🏆 Leaderboard dla {label} {emoji}",
                color=0x280586,
            )

            if not entries:
                embed.add_field(
                    name="Brak wyników",
                    value="Nikt jeszcze nie zaczął tej aktywności!",
                    inline=False,
                )
            else:
                for entry in entries:
                    try:
                        user = await self.bot.fetch_user(int(entry["discord_id"]))
                        streak_count = entry["streak_count"]
                        rank = entry["rank"]
                        embed.add_field(
                            name=f"{rank}. {user.display_name}",
                            value=f"🔥 Total: {streak_count}",
                            inline=False,
                        )
                    except Exception as e:
                        logger.error(f"Error fetching user {entry['discord_id']}: {e}")
                        continue

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error generating leaderboard: {e}")
            await interaction.response.send_message(
                "Wystąpił błąd podczas generowania rankingu. Spróbuj ponownie później.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(leaderboard(bot))
