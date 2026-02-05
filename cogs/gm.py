import discord
from discord.ext import commands
import random
import logging
from db import check_morning_checkin

logger = logging.getLogger("momentum_bot.gm")

FALLBACK_MESSAGES = [
    "Budujemy momentum!",
    "Kolejny dzień, kolejny krok!",
    "Świetny start dnia!",
    "Chodźmy, idziemy po swoje!",
]

try:
    from random_msg import random_message as WAKE_MESSAGES
except ImportError:
    logger.warning("random_msg not found, using fallback messages")
    WAKE_MESSAGES = FALLBACK_MESSAGES

try:
    from emoji import momentum_emoji as MOMENTUM_EMOJI
except ImportError:
    logger.warning("emoji not found, using fallback emoji")
    MOMENTUM_EMOJI = "🔥"


async def handle_morning_checkin(user_id: str, user_mention: str) -> str | None:
    """
    Core checkin logic shared between !gm command and gmlistener.
    Returns the reply message string, or None on DB error.
    """
    result = check_morning_checkin(user_id)

    if not result:
        logger.error("check_morning_checkin returned None for %s", user_id)
        return None

    if not result.get("success", True):
        return f"{user_mention} Za mało kawy? Tylko raz można się obudzić ☕️"

    is_early_bird = result.get("is_early_bird", False)
    total_checkins = result.get("total_checkins", 1)
    current_momentum = result.get("current_momentum", 0)

    greeting = f"🌅 **Dzień dobry {user_mention}!** " + random.choice(WAKE_MESSAGES)

    if is_early_bird:
        return (
            greeting
            + f" To twoja {total_checkins} pobudka z samego rana :raised_hands:! "
            + f"Twoje momentum wynosi {current_momentum} {MOMENTUM_EMOJI}!"
        )

    return greeting + " :raised_hands:"


class GMCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("GM command cog initialized")

    @commands.command(name="gm", description="Śledź swoje wczesne pobudki!")
    async def gm_command(self, ctx):
        try:
            reply = await handle_morning_checkin(str(ctx.author.id), ctx.author.mention)
            if reply is None:
                await ctx.send("Przepraszam, nie mogę teraz przetworzyć tego polecenia. Spróbuj ponownie później.")
                return
            await ctx.send(reply)
        except Exception as e:
            logger.error("Error in gm_command: %s", e, exc_info=True)
            await ctx.send("Wystąpił błąd podczas przetwarzania komendy. Spróbuj ponownie później.")


async def setup(bot: commands.Bot):
    await bot.add_cog(GMCommand(bot))
