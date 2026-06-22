import datetime
import logging

import discord
import pytz
from discord.ext import commands, tasks

from config import (
    DAILY_INVITE_CHANNEL_ID,
    DAILY_INVITE_VOICE_CHANNEL_ID,
    DAILY_INVITE_TIME,
)

logger = logging.getLogger("momentum_bot.daily_invite")


class DailyInviteCog(commands.Cog):
    """Posts a daily @here invite to the Daily Coaching voice channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.warsaw = pytz.timezone("Europe/Warsaw")
        self._last_sent_date = None  # guard so the @here pings at most once per day

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.schedule_invite.is_running():
            self.schedule_invite.start()
        logger.info("Daily invite scheduled for %s (channel %s)",
                    DAILY_INVITE_TIME, DAILY_INVITE_CHANNEL_ID)

    def cog_unload(self):
        self.schedule_invite.cancel()

    @tasks.loop(minutes=1)
    async def schedule_invite(self):
        now = datetime.datetime.now(self.warsaw)
        if now.strftime("%H:%M") != DAILY_INVITE_TIME or self._last_sent_date == now.date():
            return
        self._last_sent_date = now.date()

        channel = self.bot.get_channel(DAILY_INVITE_CHANNEL_ID)
        if channel is None:
            logger.error("Daily invite channel %s not found", DAILY_INVITE_CHANNEL_ID)
            return

        message = (
            f"@here, właśnie zaczynamy <#{DAILY_INVITE_VOICE_CHANNEL_ID}> - "
            f"zapraszam, jeśli jest coś, co mogę dla Was zrobić :)"
        )
        try:
            await channel.send(message, allowed_mentions=discord.AllowedMentions(everyone=True))
            logger.info("Sent daily invite at %s", now.strftime("%H:%M"))
        except Exception as e:
            logger.error("Failed to send daily invite: %s", e)

    @schedule_invite.before_loop
    async def before_schedule_invite(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(DailyInviteCog(bot))
