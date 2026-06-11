import discord
from discord.ext import commands, tasks
import logging
from datetime import datetime
import pytz
from db import log_capped_join, add_deep_work_time, get_deep_work_seconds
from config import PROGRESS_CHANNEL_ID

DAILY_COACHING_CHANNEL_ID = 1120658406160732160
DEEP_WORK_CHANNEL_ID = 1023996094524424313

DAILY_COACHING_MAX_PER_DAY = 1
DEEP_WORK_MAX_PER_DAY = 3

logger = logging.getLogger("momentum_bot.session_tracker")


def _plural_pl(n: int, one: str, few: str, many: str) -> str:
    """Polish plural selection (e.g. godzina/godziny/godzin)."""
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many


def format_duration_pl(seconds: int) -> str:
    """Format a duration in seconds as Polish 'X godzin i Y minut'."""
    minutes_total = max(seconds, 0) // 60
    hours = minutes_total // 60
    minutes = minutes_total % 60
    h_word = _plural_pl(hours, "godzina", "godziny", "godzin")
    m_word = _plural_pl(minutes, "minuta", "minuty", "minut")
    if hours > 0 and minutes > 0:
        return f"{hours} {h_word} i {minutes} {m_word}"
    if hours > 0:
        return f"{hours} {h_word}"
    return f"{minutes} {m_word}"


class SessionTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.warsaw = pytz.timezone("Europe/Warsaw")
        # user_id -> datetime of last-accounted moment (Deep Work duration)
        self.dw_ref: dict[int, datetime] = {}
        logger.info("SessionTracker cog initialized")

    @commands.Cog.listener()
    async def on_ready(self):
        # Begin tracking anyone already connected to Deep Work (e.g. after a restart)
        channel = self.bot.get_channel(DEEP_WORK_CHANNEL_ID)
        if channel:
            now = datetime.now(self.warsaw)
            for m in channel.members:
                if not m.bot and m.id not in self.dw_ref:
                    self.dw_ref[m.id] = now
        if not self.flush_deep_work.is_running():
            self.flush_deep_work.start()
        logger.info("SessionTracker cog is ready")

    def cog_unload(self):
        self.flush_deep_work.cancel()

    async def _post(self, member, main_line: str, counter_line: str):
        channel = self.bot.get_channel(PROGRESS_CHANNEL_ID)
        if not channel:
            return
        embed = discord.Embed(title="Aktywność", color=0x280586)
        embed.add_field(name="", value=main_line, inline=False)
        embed.add_field(name=counter_line, value="", inline=False)
        avatar = member.avatar or member.default_avatar
        embed.set_thumbnail(url=avatar.url)
        await channel.send(content=member.mention, embed=embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        before_id = before.channel.id if before.channel else None
        after_id = after.channel.id if after.channel else None
        if before_id == after_id:
            return  # mute/deafen/etc. — not a channel change

        # --- Daily Coaching: count joins, max 1/day ---
        if after_id == DAILY_COACHING_CHANNEL_ID:
            try:
                result = log_capped_join(
                    str(member.id), "daily_coaching", DAILY_COACHING_MAX_PER_DAY
                )
                if result and result.get("logged"):
                    n = result.get("monthly_count", 1)
                    x = result.get("total_count", n)
                    await self._post(
                        member,
                        f"To {n} Daily Coaching w tym miesiącu.",
                        f"🔢 Daily Coaching: {x}",
                    )
            except Exception as e:
                logger.error(f"Daily Coaching tracking error for {member.id}: {e}")

        # --- Deep Work: post on join (max 3/day) + track connection time ---
        if after_id == DEEP_WORK_CHANNEL_ID:
            now = datetime.now(self.warsaw)
            self.dw_ref[member.id] = now
            try:
                result = log_capped_join(
                    str(member.id), "deep_work", DEEP_WORK_MAX_PER_DAY
                )
                if result and result.get("logged"):
                    n = result.get("monthly_count", 1)
                    total = get_deep_work_seconds(str(member.id))
                    secs = total.get("total_seconds", 0) if total else 0
                    await self._post(
                        member,
                        f"To {n} sesja Deep Work w tym miesiącu.",
                        f"⚓️ Deep Work: {format_duration_pl(secs)}",
                    )
            except Exception as e:
                logger.error(f"Deep Work tracking error for {member.id}: {e}")
        elif before_id == DEEP_WORK_CHANNEL_ID:
            # Left Deep Work — bank the elapsed time
            await self._flush_member(member.id, datetime.now(self.warsaw), remove=True)

    async def _flush_member(self, uid: int, now: datetime, remove: bool):
        ref = self.dw_ref.get(uid)
        if ref is None:
            return
        seconds = int((now - ref).total_seconds())
        if remove:
            self.dw_ref.pop(uid, None)
        else:
            self.dw_ref[uid] = now
        if seconds > 0:
            try:
                add_deep_work_time(str(uid), seconds)
            except Exception as e:
                logger.error(f"Failed to add Deep Work time for {uid}: {e}")

    @tasks.loop(minutes=10)
    async def flush_deep_work(self):
        """Periodically bank time for still-connected Deep Work members so long
        sessions and bot restarts don't lose accumulated time."""
        channel = self.bot.get_channel(DEEP_WORK_CHANNEL_ID)
        if not channel:
            return
        present = {m.id for m in channel.members if not m.bot}
        now = datetime.now(self.warsaw)
        for uid in list(self.dw_ref.keys()):
            # Keep tracking present members; drop anyone who left unnoticed.
            await self._flush_member(uid, now, remove=uid not in present)

    @flush_deep_work.before_loop
    async def before_flush(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(SessionTracker(bot))
