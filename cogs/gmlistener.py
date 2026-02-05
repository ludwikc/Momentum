import re
import logging
from discord.ext import commands
from cogs.gm import handle_morning_checkin

logger = logging.getLogger("momentum_bot.gmlistener")

GM_CHANNEL_ID = 1021389566445375558


class GMListener(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("GMListener cog initialized")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if message.channel.id != GM_CHANNEL_ID:
            return

        content = message.content.lower()
        if not (re.search(r"\bgm\b", content) or "dzień dobry" in content):
            return

        try:
            reply = await handle_morning_checkin(str(message.author.id), message.author.mention)
            if reply is None:
                await message.channel.send("Przepraszam, nie mogę teraz przetworzyć tego polecenia. Spróbuj ponownie później.")
                return
            await message.channel.send(reply)
        except Exception as e:
            logger.error("Error in on_message: %s", e, exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GMListener(bot))
