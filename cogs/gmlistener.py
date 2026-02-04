import discord
from discord.ext import commands
import random
import re
import logging
from emoji import *
from random_msg import random_message
from db import check_morning_checkin

logger = logging.getLogger("momentum_bot.gmlistener")


class GMListener(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("GMListener cog initialized with Supabase")

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("GMListener cog is ready")

    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignore bot messages
        if message.author.bot:
            return

        try:
            # Check if message contains "gm" or "dzień dobry" (case insensitive)
            content = message.content.lower()
            if not (re.search(r"\bgm\b", content) or "dzień dobry" in content):
                return

            user_id = str(message.author.id)

            # Call Supabase function - handles all logic
            result = check_morning_checkin(user_id)

            if not result:
                logger.error("Supabase check_morning_checkin returned None")
                await message.channel.send(
                    "Przepraszam, nie mogę teraz przetworzyć tego polecenia. Spróbuj ponownie później."
                )
                return

            # Check if already checked in today
            if not result.get("success", True):
                await message.channel.send(
                    f"{message.author.mention} Za mało kawy? Tylko raz można się obudzić ☕️"
                )
                return

            # Build response based on early bird status
            is_early_bird = result.get("is_early_bird", False)
            total_checkins = result.get("total_checkins", 1)
            current_momentum = result.get("current_momentum", 0)

            if is_early_bird:
                emoji_to_use = momentum_emoji if "momentum_emoji" in globals() else "🔥"
                reply_message = (
                    f"🌅 **Dzień dobry {message.author.mention}!** "
                    + random.choice(random_message)
                    + f" To twoja {total_checkins} pobudka z samego rana :raised_hands:! "
                    + f"Twoje momentum wynosi {current_momentum} {emoji_to_use}!"
                )
            else:
                reply_message = (
                    f"🌅 **Dzień dobry {message.author.mention}!** "
                    + random.choice(random_message)
                    + " :raised_hands:"
                )

            await message.channel.send(reply_message)

        except Exception as e:
            logger.error(f"Error in on_message: {e}")
            import traceback

            traceback.print_exc()


async def setup(bot: commands.Bot):
    await bot.add_cog(GMListener(bot))
