import discord
from discord.ext import commands
import random
import re
import logging
from datetime import datetime
from db import check_morning_checkin

GM_CHANNEL_ID = 1021389566445375558
EMOJI_ONLY_USERS = {1413621120250417347, 1274430409391870089}

MOMENTUM_EMOJI = discord.PartialEmoji(animated=False, name='momentum', id=1224612181035978762)

GREETINGS = [
    "Miło, że jesteś tu od rana.",
    "Dobrze Cię widzieć.",
    "Cieszę się, że jesteś.",
    "Miło Cię widzieć o poranku.",
    "Dobrze widzieć znajomą energię.",
    "Hej! Dzień już pracuje na Twoją korzyść.",
    "Dzień dobry! Jesteś dokładnie tam, gdzie trzeba.",
    "GM.",
    "Super, że jesteś z nami.",
    "Witaj.",
    "Witamy.",
    "Woohoo.",
    "Mornin'!",
]

logger = logging.getLogger("momentum_bot.gmlistener")


def is_early_morning() -> bool:
    """Check if current time is between 4:00 and 6:55."""
    now = datetime.now()
    if now.hour < 4 or now.hour > 6:
        return False
    if now.hour == 6 and now.minute >= 55:
        return False
    return True


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
            # Only respond in the designated GM channel
            if message.channel.id != GM_CHANNEL_ID:
                return

            # Check if message contains "gm" or "dzień dobry" (case insensitive)
            content = message.content.lower()
            if not (re.search(r"\bgm\b", content) or "dzień dobry" in content):
                return

            # Only react during early morning hours (4:00 - 6:55)
            if not is_early_morning():
                return

            user_id = str(message.author.id)

            # Emoji-only response for specific users
            if message.author.id in EMOJI_ONLY_USERS:
                await message.reply(":optimus: :raised_hands:")
                return

            # Call Supabase function - handles all logic
            result = check_morning_checkin(user_id)

            if not result:
                logger.error("Supabase check_morning_checkin returned None")
                await message.reply(
                    "Przepraszam, nie mogę teraz przetworzyć tego polecenia. Spróbuj ponownie później."
                )
                return

            # Check if already checked in today
            if not result.get("success", True):
                await message.reply(f"😂 {message.author.mention} Za mało kawy? Tylko raz można się obudzić ☕️")
                return

            # Build response - greeting + streak, no quote
            greeting = random.choice(GREETINGS)
            current_momentum = result.get("current_momentum", 0)
            total_checkins = result.get("total_checkins", 1)

            reply_message = (
                f"{greeting}\n"
                f"To twoja {total_checkins} pobudka z samego rana! "
                f"Twoje momentum wynosi {current_momentum} {MOMENTUM_EMOJI}!"
            )

            await message.reply(reply_message)

        except Exception as e:
            logger.error(f"Error in on_message: {e}")
            import traceback

            traceback.print_exc()


async def setup(bot: commands.Bot):
    await bot.add_cog(GMListener(bot))
