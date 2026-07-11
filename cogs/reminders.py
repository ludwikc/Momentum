"""Przypomnienia — /przypomnij, /przypomnienia (StudyLion reminders port).

DM-only delivery with an upfront DM-ability probe (an empty send raises
Forbidden when DMs are closed and a harmless HTTPException when open —
StudyLion's trick). The per-minute poller fetches due reminders and acks each
after the send attempt: repeating ones advance past all missed occurrences
anchored to the original time (no burst after downtime, no drift); one-shots
are deleted; failures are flagged and never retried.
"""
import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
from datetime import datetime, timedelta
import pytz

from config import (
    REMINDER_MAX_CONTENT,
    REMINDER_MAX_PER_USER,
    REMINDER_MIN_REPEAT_SECONDS,
)
from db import reminder_ack, reminder_add, reminder_cancel, reminder_list, reminders_due
from parsers import parse_duration_pl, parse_index_ranges, parse_wallclock_pl

logger = logging.getLogger("momentum_bot.reminders")

DB_ERROR_MSG = "Wystąpił błąd bazy danych. Spróbuj ponownie później."


def _parse_db_ts(value: str) -> datetime:
    """PostgREST timestamptz JSON → aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_every(seconds: int) -> str:
    """'co 3h', 'co 1d 2h 30m' — compact Polish interval rendering."""
    parts = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount}{unit}")
    if seconds:
        parts.append(f"{seconds}s")
    return "co " + " ".join(parts)


class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.warsaw = pytz.timezone("Europe/Warsaw")
        logger.info("Reminders cog initialized")

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.poll_due.is_running():
            self.poll_due.start()
        logger.info("Reminders cog is ready")

    def cog_unload(self):
        self.poll_due.cancel()

    async def _dms_open(self, user: discord.User | discord.Member) -> bool:
        """StudyLion's probe: an empty send fails with Forbidden only when the
        user can't be DM'd; when DMs are open it fails harmlessly (400)."""
        try:
            await user.send("")
        except discord.Forbidden:
            return False
        except discord.HTTPException:
            return True
        return True

    @app_commands.command(
        name="przypomnij",
        description="Ustaw przypomnienie (na DM) — za jakiś czas albo o godzinie",
    )
    @app_commands.describe(
        tekst="O czym przypomnieć",
        za="Za ile czasu, np. `30m`, `3h`, `1d 2h` (sama liczba = minuty)",
        o="O której, np. `16:00` albo `2026-07-15 09:00` (czas warszawski)",
        co="Powtarzaj co, np. `1d` albo `3h` (min. 10 minut)",
    )
    async def przypomnij(
        self,
        interaction: discord.Interaction,
        tekst: str,
        za: str | None = None,
        o: str | None = None,
        co: str | None = None,
    ):
        tekst = tekst.strip()
        if not tekst or len(tekst) > REMINDER_MAX_CONTENT:
            await interaction.response.send_message(
                f"Treść musi mieć 1–{REMINDER_MAX_CONTENT} znaków.", ephemeral=True
            )
            return
        if bool(za) == bool(o):
            await interaction.response.send_message(
                "Podaj **jedno** z dwóch: `za` (np. `3h`) albo `o` (np. `16:00`).",
                ephemeral=True,
            )
            return

        now_warsaw = datetime.now(self.warsaw)
        if za:
            seconds = parse_duration_pl(za)
            if not seconds or seconds <= 0:
                await interaction.response.send_message(
                    "Nie rozumiem `za` — podaj np. `30m`, `3h`, `1d 2h` "
                    "(sama liczba = minuty).",
                    ephemeral=True,
                )
                return
            remind_at = now_warsaw + timedelta(seconds=seconds)
        else:
            naive = parse_wallclock_pl(o, now_warsaw.replace(tzinfo=None))
            if naive is None:
                await interaction.response.send_message(
                    "Nie rozumiem `o` — podaj np. `16:00` albo `2026-07-15 09:00`.",
                    ephemeral=True,
                )
                return
            remind_at = self.warsaw.localize(naive)
            if remind_at <= now_warsaw:
                await interaction.response.send_message(
                    "Ten moment już minął — podaj czas w przyszłości.", ephemeral=True
                )
                return

        every_seconds = None
        if co:
            every_seconds = parse_duration_pl(co)
            if not every_seconds:
                await interaction.response.send_message(
                    "Nie rozumiem `co` — podaj np. `3h` albo `1d`.", ephemeral=True
                )
                return
            if every_seconds < REMINDER_MIN_REPEAT_SECONDS:
                await interaction.response.send_message(
                    f"Powtarzanie nie może być częstsze niż co "
                    f"{REMINDER_MIN_REPEAT_SECONDS // 60} minut.",
                    ephemeral=True,
                )
                return

        try:
            if not await self._dms_open(interaction.user):
                await interaction.response.send_message(
                    "Nie mogę wysłać Ci prywatnej wiadomości! Włącz DM od członków "
                    "serwera (Ustawienia serwera → Prywatność) i spróbuj ponownie.",
                    ephemeral=True,
                )
                return

            result = reminder_add(
                str(interaction.user.id),
                tekst,
                remind_at.isoformat(),
                every_seconds,
                REMINDER_MAX_PER_USER,
                REMINDER_MIN_REPEAT_SECONDS,
            )
            if not result or not result.get("ok"):
                error = (result or {}).get("error")
                if error == "limit":
                    msg = (
                        f"Masz już {REMINDER_MAX_PER_USER} przypomnień — usuń "
                        f"któreś przez `/przypomnienia usun:<numer>`."
                    )
                elif error == "past":
                    msg = "Ten moment już minął — podaj czas w przyszłości."
                elif error == "min_interval":
                    msg = (
                        f"Powtarzanie nie może być częstsze niż co "
                        f"{REMINDER_MIN_REPEAT_SECONDS // 60} minut."
                    )
                else:
                    msg = DB_ERROR_MSG
                await interaction.response.send_message(msg, ephemeral=True)
                return

            ts = int(remind_at.timestamp())
            embed = discord.Embed(
                title="⏰ Przypomnienie ustawione!",
                description=tekst,
                color=0x2ECC71,
            )
            embed.add_field(name="Kiedy", value=f"<t:{ts}:F> (<t:{ts}:R>)", inline=False)
            if every_seconds:
                embed.add_field(
                    name="Powtarzanie", value=_format_every(every_seconds), inline=False
                )
            embed.set_footer(text="Dostaniesz prywatną wiadomość. Lista: /przypomnienia")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in /przypomnij: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @app_commands.command(
        name="przypomnienia",
        description="Pokaż lub usuń swoje przypomnienia",
    )
    @app_commands.describe(usun="Numery do usunięcia, np. `2` albo `1,3` albo `all`")
    async def przypomnienia(
        self, interaction: discord.Interaction, usun: str | None = None
    ):
        try:
            rows = reminder_list(str(interaction.user.id))

            if usun:
                if not rows:
                    await interaction.response.send_message(
                        "Nie masz żadnych przypomnień.", ephemeral=True
                    )
                    return
                indices = parse_index_ranges(usun, len(rows))
                if indices is None:
                    await interaction.response.send_message(
                        "Nie rozumiem tych numerów — podaj np. `2`, `1,3` albo `all`.",
                        ephemeral=True,
                    )
                    return
                ids = [rows[i - 1]["id"] for i in indices]
                result = reminder_cancel(str(interaction.user.id), ids)
                removed = (result or {}).get("removed", 0)
                await interaction.response.send_message(
                    f"🗑️ Usunięto {removed} przypomnień.", ephemeral=True
                )
                return

            embed = discord.Embed(title="⏰ Twoje przypomnienia", color=0x280586)
            if not rows:
                embed.description = (
                    "Pusto! Ustaw pierwsze: `/przypomnij tekst:… za:3h` "
                    "albo `… o:16:00` (opcjonalnie `co:1d`)."
                )
            else:
                lines = []
                for idx, row in enumerate(rows, start=1):
                    ts = int(_parse_db_ts(row["remind_at"]).timestamp())
                    line = f"**[{idx}]** <t:{ts}:R> — {row['content'][:60]}"
                    if row.get("every_seconds"):
                        line += f" ({_format_every(row['every_seconds'])})"
                    if row.get("failed"):
                        line += " ⚠️ nieudane (DM zablokowane?)"
                    lines.append(line)
                embed.description = "\n".join(lines)
                embed.set_footer(text="Usuń: /przypomnienia usun:<numer>")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in /przypomnienia: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @tasks.loop(minutes=1)
    async def poll_due(self):
        try:
            due = reminders_due()
        except Exception as e:
            logger.error(f"Failed to fetch due reminders: {e}")
            return

        for row in due:
            ok = False
            try:
                user = self.bot.get_user(int(row["discord_id"]))
                if user is None:
                    user = await self.bot.fetch_user(int(row["discord_id"]))

                embed = discord.Embed(
                    title="⏰ Prosiłeś/aś o przypomnienie!",
                    description=row["content"],
                    color=0xE67E22,
                )
                every = row.get("every_seconds")
                if every:
                    remind_at = _parse_db_ts(row["remind_at"])
                    now = datetime.now(pytz.utc)
                    periods = int((now - remind_at).total_seconds() // every) + 1
                    next_at = remind_at + timedelta(seconds=periods * every)
                    embed.add_field(
                        name="Następne",
                        value=f"<t:{int(next_at.timestamp())}:R>",
                        inline=False,
                    )
                    embed.set_footer(text="Usuń: /przypomnienia usun:<numer>")
                await user.send(embed=embed)
                ok = True
            except Exception as e:
                logger.warning(
                    f"Reminder {row.get('id')} delivery failed "
                    f"for {row.get('discord_id')}: {e}"
                )
            try:
                reminder_ack(row["id"], ok)
            except Exception as e:
                logger.error(f"Failed to ack reminder {row.get('id')}: {e}")

    @poll_due.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Reminders(bot))
