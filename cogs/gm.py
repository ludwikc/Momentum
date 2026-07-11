import discord
from discord import app_commands
from discord.ext import commands
import random
import logging
from random_msg import random_message
from config import COINS_EMOJI, GM_REWARD_COINS
from db import award_coins_safe, check_morning_checkin

GM_CHANNEL_ID = 1021389566445375558
EMOJI_ONLY_USERS = {1413621120250417347, 1274430409391870089}

MOMENTUM_EMOJI = discord.PartialEmoji(animated=False, name='momentum', id=1224612181035978762)

logger = logging.getLogger("momentum_bot.gm")


class GMCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("GM command cog initialized with Supabase")

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("GM command cog is ready")

    @app_commands.command(name="gm", description="Śledź swoje wczesne pobudki!")
    async def gm_command(self, interaction: discord.Interaction):
        try:
            # Only respond in the designated GM channel
            if interaction.channel_id != GM_CHANNEL_ID:
                await interaction.response.send_message(
                    "Ta komenda działa tylko na kanale GM.",
                    ephemeral=True,
                )
                return

            # Emoji-only response for specific users
            if interaction.user.id in EMOJI_ONLY_USERS:
                await interaction.response.send_message(":optimus: :raised_hands:")
                return

            user_id = str(interaction.user.id)

            # Call Supabase function - handles all logic
            result = check_morning_checkin(user_id)

            if not result:
                logger.error("Supabase check_morning_checkin returned None")
                await interaction.response.send_message(
                    "Przepraszam, nie mogę teraz przetworzyć tego polecenia. Spróbuj ponownie później.",
                    ephemeral=True,
                )
                return

            # Check if already checked in today
            if not result.get("success", True):
                await interaction.response.send_message(
                    f"😂 {interaction.user.mention} Za mało kawy? Tylko raz można się obudzić ☕️"
                )
                return

            # Build public response: "GM @user" + optional streak
            current_momentum = result.get("current_momentum", 0)

            if current_momentum > 0:
                public_message = (
                    f"GM {interaction.user.mention} "
                    f"| Momentum: {current_momentum} {MOMENTUM_EMOJI}"
                )
            else:
                public_message = f"GM {interaction.user.mention}"

            # StudyLion-port economy hook: small coin bonus for the check-in.
            if award_coins_safe(user_id, GM_REWARD_COINS, "gm"):
                public_message += f" (+{GM_REWARD_COINS} {COINS_EMOJI})"

            # Send public response
            await interaction.response.send_message(public_message)

            # Send quote as ephemeral follow-up (visible only to the user)
            quote = random.choice(random_message)
            await interaction.followup.send(quote, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in gm_command: {e}")
            import traceback

            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Wystąpił błąd podczas przetwarzania komendy. Spróbuj ponownie później.",
                    ephemeral=True,
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(GMCommand(bot))
