import discord
from discord.ext import commands
import random
import logging
from random_msg import random_message
from db import check_morning_checkin

MOMENTUM_EMOJI = discord.PartialEmoji(animated=False, name='momentum', id=1224612181035978762)

logger = logging.getLogger("momentum_bot.gm")


class GMCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("GM command cog initialized with Supabase")

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("GM command cog is ready")

    @commands.command(name="gm", description="Śledź swoje wczesne pobudki!")
    async def gm_command(self, ctx):
        try:
            user_id = str(ctx.author.id)

            # Call Supabase function - handles all logic
            result = check_morning_checkin(user_id)

            if not result:
                logger.error("Supabase check_morning_checkin returned None")
                await ctx.send(
                    "Przepraszam, nie mogę teraz przetworzyć tego polecenia. Spróbuj ponownie później."
                )
                return

            # Check if already checked in today
            if not result.get("success", True):
                await ctx.send("Za mało kawy? Tylko raz można się obudzić ☕️")
                return

            # Build response based on early bird status
            is_early_bird = result.get("is_early_bird", False)
            total_checkins = result.get("total_checkins", 1)
            current_momentum = result.get("current_momentum", 0)

            if is_early_bird:
                emoji_to_use = MOMENTUM_EMOJI
                reply_message = (
                    f"🌅 **Dzień dobry {ctx.author.mention}!** "
                    + random.choice(random_message)
                    + f" To twoja {total_checkins} pobudka z samego rana :raised_hands:! "
                    + f"Twoje momentum wynosi {current_momentum} {emoji_to_use}!"
                )
            else:
                reply_message = (
                    f"🌅 **Dzień dobry {ctx.author.mention}!** "
                    + random.choice(random_message)
                    + " :raised_hands:"
                )

            await ctx.send(reply_message)

        except Exception as e:
            logger.error(f"Error in gm_command: {e}")
            import traceback

            traceback.print_exc()
            await ctx.send(
                "Wystąpił błąd podczas przetwarzania komendy. Spróbuj ponownie później."
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(GMCommand(bot))
