import discord
from discord.ext import commands, tasks
import logging
from datetime import datetime, timedelta
import pytz
from db import upsert_activity, get_user_activity_stats
from config import ACTIVITIES as act, PROGRESS_CHANNEL_ID

MEDITATION_VOICE_CHANNEL_ID = 988452597549641758
MIN_DURATION = timedelta(minutes=10)
WELCOME_MESSAGE = "Dziękuję, że jesteś i medytujesz z nami."

logger = logging.getLogger("momentum_bot.meditation_voice")


class MeditationVoiceListener(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.warsaw = pytz.timezone("Europe/Warsaw")
        # user_id -> Warsaw-aware join time
        self.join_times: dict[int, datetime] = {}
        # user_ids already credited this session (dedupe)
        self.logged: set[int] = set()
        logger.info("MeditationVoiceListener cog initialized")

    def _in_window(self, now: datetime) -> bool:
        """Tuesday, 06:00-06:59 Warsaw time."""
        return now.weekday() == 1 and now.hour == 6

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.sweep_stragglers.is_running():
            self.sweep_stragglers.start()
        logger.info("MeditationVoiceListener cog is ready")

    def cog_unload(self):
        self.sweep_stragglers.cancel()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        joined = (
            (before.channel is None or before.channel.id != MEDITATION_VOICE_CHANNEL_ID)
            and after.channel is not None
            and after.channel.id == MEDITATION_VOICE_CHANNEL_ID
        )
        left = (
            before.channel is not None
            and before.channel.id == MEDITATION_VOICE_CHANNEL_ID
            and (after.channel is None or after.channel.id != MEDITATION_VOICE_CHANNEL_ID)
        )

        now = datetime.now(self.warsaw)

        if joined:
            if not self._in_window(now) or member.id in self.logged:
                return
            self.join_times[member.id] = now
            try:
                await member.send(WELCOME_MESSAGE)
            except discord.Forbidden:
                logger.info(f"Could not DM welcome to {member.id} (DMs closed)")
            except Exception as e:
                logger.error(f"Error sending welcome DM to {member.id}: {e}")

        elif left:
            join_time = self.join_times.pop(member.id, None)
            if join_time is None:
                return
            duration = now - join_time
            if duration >= MIN_DURATION and member.id not in self.logged:
                await self._credit(member)
                self.logged.add(member.id)

    async def _credit(self, member):
        """Log a medytacja streak and post it to the progress channel."""
        user_id = str(member.id)
        try:
            result = upsert_activity(user_id, "medytacja")
            if not result:
                logger.error("upsert_activity returned None for meditation credit")
                return

            streak_count = result.get("streak_count", 1)

            embed = discord.Embed(title="Aktywność", color=0x280586)
            embed.add_field(
                name="",
                value=f"🔥 To {streak_count} medytacja w tym miesiącu!",
            )

            avatar = member.avatar or member.default_avatar
            embed.set_thumbnail(url=avatar.url)

            all_stats = get_user_activity_stats(user_id)
            if all_stats:
                for name, emoji in act.items():
                    streak_key = f"streak_{name}"
                    count = all_stats.get(streak_key, 0)
                    if count > 0:
                        embed.add_field(
                            name=f"{emoji} {name.capitalize()}: {count}",
                            value="",
                            inline=False,
                        )

            channel = self.bot.get_channel(PROGRESS_CHANNEL_ID)
            if channel:
                await channel.send(content=member.mention, embed=embed)

        except Exception as e:
            logger.error(f"Error crediting meditation for {member.id}: {e}")

    @tasks.loop(minutes=1)
    async def sweep_stragglers(self):
        """Credit members still connected once the join window has closed."""
        now = datetime.now(self.warsaw)
        if not self.join_times or self._in_window(now):
            return

        channel = self.bot.get_channel(MEDITATION_VOICE_CHANNEL_ID)
        for uid, join_time in list(self.join_times.items()):
            if (now - join_time) >= MIN_DURATION and uid not in self.logged:
                member = channel.guild.get_member(uid) if channel else None
                if member:
                    await self._credit(member)
                    self.logged.add(uid)

        self.join_times.clear()
        self.logged.clear()

    @sweep_stragglers.before_loop
    async def before_sweep(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(MeditationVoiceListener(bot))
