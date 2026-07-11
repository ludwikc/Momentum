"""Voice-time tracking across all voice channels (StudyLion tracking port).

Per-Warsaw-day aggregates via the add_voice_time RPC, which also mints coins
(VOICE_COINS_PER_HOUR, capped at VOICE_COIN_DAILY_CAP_HOURS per day) with the
ledger as the anti-double-mint source of truth. Mirrors session_tracker's
proven shape: refs dict + on_ready seeding + periodic flush (bounds restart
loss to <VOICE_FLUSH_MINUTES). After each flush a `momentum_voice_flushed`
event is dispatched for the ranks cog.
"""
from discord.ext import commands, tasks
import logging
from datetime import datetime
import pytz

from config import (
    UNTRACKED_VOICE_CHANNEL_IDS,
    VOICE_COIN_DAILY_CAP_HOURS,
    VOICE_COINS_PER_HOUR,
    VOICE_FLUSH_MINUTES,
)
from db import add_voice_time

logger = logging.getLogger("momentum_bot.voice_tracker")


class VoiceTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.warsaw = pytz.timezone("Europe/Warsaw")
        # user_id -> (channel_id, datetime of last-accounted moment)
        self.refs: dict[int, tuple[int, datetime]] = {}
        logger.info("VoiceTracker cog initialized")

    def _tracked(self, channel) -> bool:
        return channel is not None and channel.id not in UNTRACKED_VOICE_CHANNEL_IDS

    @commands.Cog.listener()
    async def on_ready(self):
        # Seed anyone already connected (e.g. after a restart).
        now = datetime.now(self.warsaw)
        for guild in self.bot.guilds:
            for channel in list(guild.voice_channels) + list(guild.stage_channels):
                if not self._tracked(channel):
                    continue
                for m in channel.members:
                    if not m.bot and m.id not in self.refs:
                        self.refs[m.id] = (channel.id, now)
        if not self.flush_all.is_running():
            self.flush_all.start()
        logger.info(f"VoiceTracker cog is ready ({len(self.refs)} members seeded)")

    def cog_unload(self):
        self.flush_all.cancel()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        before_id = before.channel.id if before.channel else None
        after_id = after.channel.id if after.channel else None
        if before_id == after_id:
            return  # mute/deafen/etc.

        now = datetime.now(self.warsaw)
        if self._tracked(before.channel):
            await self._flush(member.id, now, remove=True)
        if self._tracked(after.channel):
            self.refs[member.id] = (after_id, now)

    async def _flush(self, uid: int, now: datetime, remove: bool):
        ref = self.refs.get(uid)
        if ref is None:
            return
        channel_id, since = ref
        seconds = int((now - since).total_seconds())
        if remove:
            self.refs.pop(uid, None)
        else:
            self.refs[uid] = (channel_id, now)
        if seconds <= 0:
            return
        try:
            result = add_voice_time(
                str(uid),
                str(channel_id),
                seconds,
                VOICE_COINS_PER_HOUR,
                VOICE_COIN_DAILY_CAP_HOURS * 3600,
            )
            total = (result or {}).get("total_seconds", 0)
            # Ranks cog listens for this (decoupled award check).
            self.bot.dispatch("momentum_voice_flushed", uid, total)
        except Exception as e:
            logger.error(f"Failed to add voice time for {uid}: {e}")

    @tasks.loop(minutes=VOICE_FLUSH_MINUTES)
    async def flush_all(self):
        """Bank time for still-connected members; drop anyone who left
        unnoticed (same policy as session_tracker's Deep Work flush)."""
        present: dict[int, int] = {}
        for guild in self.bot.guilds:
            for channel in list(guild.voice_channels) + list(guild.stage_channels):
                if not self._tracked(channel):
                    continue
                for m in channel.members:
                    if not m.bot:
                        present[m.id] = channel.id
        now = datetime.now(self.warsaw)
        for uid in list(self.refs.keys()):
            await self._flush(uid, now, remove=uid not in present)
        # Anyone connected but unknown (e.g. joined during a gap) starts now.
        for uid, channel_id in present.items():
            if uid not in self.refs:
                self.refs[uid] = (channel_id, now)

    @flush_all.before_loop
    async def before_flush(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceTracker(bot))
