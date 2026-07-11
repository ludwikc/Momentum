"""Pomodoro — /pomodoro start|stop|status (StudyLion timer port).

One timer per voice channel; the whole cycle derives from the `last_started`
anchor (pomodoro_math.current_stage), so timers resume mid-cycle after a bot
restart. Stage changes are announced in the voice channel's built-in text chat
with a native live countdown (<t:…:R>) — deliberately instead of StudyLion's
rate-limited channel renames. Empty channel at a stage boundary stops the
timer with auto_restart: the next join starts the cycle fresh.
"""
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import logging
from datetime import datetime, timezone
import pytz

from config import (
    POMODORO_DEFAULT_BREAK_MIN,
    POMODORO_DEFAULT_FOCUS_MIN,
    POMODORO_MAX_STAGE_MIN,
)
from db import pomodoro_delete, pomodoro_list_all, pomodoro_set_stopped, pomodoro_upsert
from parsers import parse_db_timestamp
from pomodoro_math import current_stage

logger = logging.getLogger("momentum_bot.pomodoro")

DB_ERROR_MSG = "Wystąpił błąd bazy danych. Spróbuj ponownie później."
MAX_SLEEP = 300  # chunked sleeps (StudyLion drift guard)


class TimerState:
    def __init__(
        self,
        focus_seconds: int,
        break_seconds: int,
        last_started: datetime | None,
        auto_restart: bool,
        started_by: str | None,
    ):
        self.focus_seconds = focus_seconds
        self.break_seconds = break_seconds
        self.last_started = last_started
        self.auto_restart = auto_restart
        self.started_by = started_by
        self.task: asyncio.Task | None = None
        self.last_stage: str | None = None

    @property
    def running(self) -> bool:
        return self.last_started is not None

    @property
    def pattern(self) -> str:
        return f"{self.focus_seconds // 60}/{self.break_seconds // 60}"


@app_commands.guild_only()
class Pomodoro(commands.GroupCog, group_name="pomodoro", description="Wspólny timer pomodoro na kanale głosowym"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.warsaw = pytz.timezone("Europe/Warsaw")
        self.timers: dict[int, TimerState] = {}
        logger.info("Pomodoro cog initialized")

    @commands.Cog.listener()
    async def on_ready(self):
        """Restore timers from Supabase; running ones resume mid-cycle."""
        try:
            rows = pomodoro_list_all()
        except Exception as e:
            logger.error(f"Failed to load pomodoro timers: {e}")
            return
        for row in rows:
            # Per-row guard: one malformed row must not abort the whole resume.
            try:
                channel_id = int(row["channel_id"])
                if channel_id in self.timers:
                    continue
                last_started = (
                    parse_db_timestamp(row["last_started"])
                    if row.get("last_started")
                    else None
                )
                state = TimerState(
                    row["focus_seconds"],
                    row["break_seconds"],
                    last_started,
                    row.get("auto_restart", False),
                    row.get("started_by"),
                )
                if self.bot.get_channel(channel_id) is None:
                    # Channel vanished while we were offline.
                    try:
                        pomodoro_delete(str(channel_id))
                    except Exception:
                        pass
                    continue
                self.timers[channel_id] = state
                if state.running:
                    state.task = asyncio.create_task(self._run_timer(channel_id))
                    logger.info(f"Resumed pomodoro in channel {channel_id}")
            except Exception as e:
                logger.error(f"Failed to restore pomodoro row {row!r}: {e}")
        logger.info("Pomodoro cog is ready")

    def cog_unload(self):
        for state in self.timers.values():
            if state.task:
                state.task.cancel()

    # --- timer loop -------------------------------------------------------

    async def _run_timer(self, channel_id: int):
        state = self.timers.get(channel_id)
        try:
            while state and state.running:
                channel = self.bot.get_channel(channel_id)
                if channel is None:
                    # Channel deleted — drop the timer entirely.
                    self.timers.pop(channel_id, None)
                    try:
                        pomodoro_delete(str(channel_id))
                    except Exception:
                        pass
                    return

                now = datetime.now(timezone.utc)
                stage, _, stage_end = current_stage(
                    state.last_started, state.focus_seconds, state.break_seconds, now
                )

                if stage != state.last_stage:
                    members = [m for m in channel.members if not m.bot]
                    if not members:
                        # Empty at a boundary → stop; next join restarts.
                        await self._stop(channel_id, auto_restart=True)
                        return
                    state.last_stage = stage
                    await self._announce_stage(channel, state, stage, stage_end, members)

                remaining = (stage_end - datetime.now(timezone.utc)).total_seconds()
                await asyncio.sleep(max(1.0, min(MAX_SLEEP, remaining + 0.5)))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Pomodoro loop error for channel {channel_id}: {e}")

    async def _announce_stage(self, channel, state, stage, stage_end, members):
        ts = int(stage_end.timestamp())
        if stage == "focus":
            line = f"🍅 **Fokus!** ({state.pattern}) Przerwa <t:{ts}:R>."
        else:
            line = f"☕ **Przerwa!** Kolejny fokus <t:{ts}:R>."
        mentions = " ".join(m.mention for m in members)
        try:
            await channel.send(f"{line} ||{mentions}||")
        except Exception as e:
            logger.warning(f"Pomodoro announce failed in {channel.id}: {e}")
        # Best-effort voice-channel status (nice-to-have; API/permission
        # differences must never kill the loop).
        try:
            end_local = stage_end.astimezone(self.warsaw).strftime("%H:%M")
            label = "🍅 Fokus" if stage == "focus" else "☕ Przerwa"
            await channel.edit(status=f"{label} do {end_local}")
        except Exception:
            pass

    async def _stop(self, channel_id: int, auto_restart: bool):
        state = self.timers.get(channel_id)
        if not state:
            return
        state.last_started = None
        state.auto_restart = auto_restart
        state.last_stage = None
        if state.task and state.task is not asyncio.current_task():
            state.task.cancel()
        state.task = None
        try:
            pomodoro_set_stopped(str(channel_id), auto_restart)
        except Exception as e:
            logger.error(f"Failed to persist pomodoro stop for {channel_id}: {e}")
        channel = self.bot.get_channel(channel_id)
        if channel:
            try:
                await channel.edit(status=None)
            except Exception:
                pass

    def _start_state(self, channel_id: int, state: TimerState, started_by: str):
        state.last_started = datetime.now(timezone.utc)
        state.auto_restart = False
        state.started_by = started_by
        state.last_stage = None
        if state.task:
            state.task.cancel()
        state.task = asyncio.create_task(self._run_timer(channel_id))

    # --- auto-restart on join (StudyLion behavior) -------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot or after.channel is None:
            return
        if before.channel and before.channel.id == after.channel.id:
            return
        state = self.timers.get(after.channel.id)
        if state and not state.running and state.auto_restart:
            self._start_state(after.channel.id, state, state.started_by or str(member.id))
            try:
                pomodoro_upsert(
                    str(after.channel.id), state.focus_seconds, state.break_seconds,
                    state.last_started.isoformat(), state.started_by or str(member.id),
                )
            except Exception as e:
                logger.error(f"Failed to persist pomodoro auto-restart: {e}")
            logger.info(f"Pomodoro auto-restarted in {after.channel.id} by {member.id}")

    # --- commands -----------------------------------------------------------

    def _caller_channel(self, interaction: discord.Interaction):
        voice = getattr(interaction.user, "voice", None)
        return voice.channel if voice and voice.channel else None

    @app_commands.command(name="start", description="Wystartuj (lub zrestartuj) pomodoro na swoim kanale głosowym")
    @app_commands.describe(
        fokus=f"Długość fokusa w minutach (domyślnie {POMODORO_DEFAULT_FOCUS_MIN})",
        przerwa=f"Długość przerwy w minutach (domyślnie {POMODORO_DEFAULT_BREAK_MIN})",
    )
    async def start(
        self,
        interaction: discord.Interaction,
        fokus: app_commands.Range[int, 1, POMODORO_MAX_STAGE_MIN] = POMODORO_DEFAULT_FOCUS_MIN,
        przerwa: app_commands.Range[int, 1, POMODORO_MAX_STAGE_MIN] = POMODORO_DEFAULT_BREAK_MIN,
    ):
        channel = self._caller_channel(interaction)
        if channel is None:
            await interaction.response.send_message(
                "Wejdź najpierw na kanał głosowy, na którym ma działać timer.",
                ephemeral=True,
            )
            return
        try:
            restarted = channel.id in self.timers and self.timers[channel.id].running
            state = self.timers.get(channel.id) or TimerState(
                fokus * 60, przerwa * 60, None, False, str(interaction.user.id)
            )
            state.focus_seconds = fokus * 60
            state.break_seconds = przerwa * 60
            self.timers[channel.id] = state
            self._start_state(channel.id, state, str(interaction.user.id))
            pomodoro_upsert(
                str(channel.id), state.focus_seconds, state.break_seconds,
                state.last_started.isoformat(), str(interaction.user.id),
            )
            ts = int((state.last_started.timestamp()) + state.focus_seconds)
            verb = "zrestartowane" if restarted else "wystartowało"
            await interaction.response.send_message(
                f"🍅 Pomodoro {verb} na {channel.mention}: **{state.pattern}**. "
                f"Pierwsza przerwa <t:{ts}:R>. Powodzenia!"
            )
        except Exception as e:
            logger.error(f"Error in /pomodoro start: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="stop", description="Zatrzymaj pomodoro na swoim kanale głosowym")
    async def stop(self, interaction: discord.Interaction):
        channel = self._caller_channel(interaction)
        if channel is None:
            await interaction.response.send_message(
                "Wejdź na kanał głosowy z timerem, który chcesz zatrzymać.",
                ephemeral=True,
            )
            return
        state = self.timers.get(channel.id)
        if not state or not state.running:
            await interaction.response.send_message(
                "Na tym kanale nie działa żaden timer.", ephemeral=True
            )
            return
        try:
            await self._stop(channel.id, auto_restart=False)
            await interaction.response.send_message(
                f"⏹️ Pomodoro na {channel.mention} zatrzymane."
            )
        except Exception as e:
            logger.error(f"Error in /pomodoro stop: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="status", description="Pokaż stan pomodoro na swoim kanale głosowym")
    async def status(self, interaction: discord.Interaction):
        channel = self._caller_channel(interaction)
        if channel is None:
            await interaction.response.send_message(
                "Wejdź na kanał głosowy, żeby sprawdzić jego timer.", ephemeral=True
            )
            return
        state = self.timers.get(channel.id)
        if not state:
            await interaction.response.send_message(
                "Na tym kanale nie ma timera — wystartuj: `/pomodoro start`.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(title="🍅 Pomodoro", color=0x280586)
        embed.add_field(name="Kanał", value=channel.mention, inline=False)
        embed.add_field(name="Wzór", value=state.pattern, inline=False)
        if state.running:
            stage, _, stage_end = current_stage(
                state.last_started, state.focus_seconds, state.break_seconds,
                datetime.now(timezone.utc),
            )
            ts = int(stage_end.timestamp())
            label = "🍅 Fokus" if stage == "focus" else "☕ Przerwa"
            embed.add_field(
                name="Teraz", value=f"{label} — koniec <t:{ts}:R>", inline=False
            )
        else:
            hint = (
                "zatrzymany — wystartuje, gdy ktoś wejdzie na kanał"
                if state.auto_restart
                else "zatrzymany — `/pomodoro start`"
            )
            embed.add_field(name="Teraz", value=f"⏹️ {hint}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Pomodoro(bot))
