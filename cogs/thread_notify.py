import discord
from discord.ext import commands
import logging

logger = logging.getLogger("momentum_bot.thread_notify")

WATCHED_CHANNEL_ID = 1124379257586593957
NOTIFY_MESSAGE = "Ping <&1109472432387002408>, zobaczcie ten wątek!"


class ThreadNotify(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if thread.parent_id != WATCHED_CHANNEL_ID:
            return
        try:
            await thread.send(NOTIFY_MESSAGE)
            logger.info(f"Sent notification in new thread {thread.id} (parent {thread.parent_id})")
        except Exception as e:
            logger.error(f"Failed to send thread notification in {thread.id}: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(ThreadNotify(bot))
