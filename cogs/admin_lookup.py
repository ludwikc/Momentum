"""/admin transkrypt — link do transkryptu + audio z Google Drive dla danej daty.

Spec: docs/superpowers/specs/2026-08-18-drive-transcript-md-admin-lookup.md.

Uzupełnienie pipeline'u nagrywania (cogs/voicerecord.py): od tej zmiany pełny
transkrypt trafia na Drive jako `<stem-audio>-transcript.md` obok mp3 (wcześniej
bywał tylko bare .txt). To narzędzie pozwala administratorowi znaleźć oba pliki
bez grzebania ręcznie w Drive — po prostu podaje datę spotkania.
"""
import asyncio
import logging
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

import gdrive
from parsers import parse_date_arg, parse_recording_filename

logger = logging.getLogger("momentum_bot.admin_lookup")

WARSAW = ZoneInfo("Europe/Warsaw")

_TRANSCRIPT_SUFFIXES = ("-transcript.md", ".md", ".txt", ".mp3")


def _strip_known_suffix(name: str) -> str:
    for suf in _TRANSCRIPT_SUFFIXES:
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


def _group_meetings(files: list[dict]) -> dict:
    """Group Drive files by recording key (started, slug, rec_id).

    Each file's name (minus a known suffix) is reparsed as a recorder filename
    stem (+".wav") to recover the (started, slug, rec_id) triple, which is the
    shared join key between the audio and its transcript sidecar.
    """
    meetings: dict = {}
    for f in files:
        base = _strip_known_suffix(f["name"])
        parsed = parse_recording_filename(base + ".wav")
        if parsed is None:
            continue
        key = parsed  # (started, slug, rec_id) — hashable tuple
        entry = meetings.setdefault(key, {"audio": None, "transcript_md": None, "transcript_txt": None})
        name = f["name"]
        if name.endswith("-transcript.md"):
            entry["transcript_md"] = f
        elif name.endswith(".txt"):
            entry["transcript_txt"] = f
        elif name.endswith(".mp3"):
            entry["audio"] = f
    return meetings


class AdminLookup(commands.Cog):
    """/admin transkrypt — znajdź transkrypt + audio spotkania na Drive po dacie."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    admin = app_commands.Group(
        name="admin", description="Narzędzia administracyjne Momentum",
        guild_only=True, default_permissions=discord.Permissions(administrator=True),
    )

    @admin.command(name="transkrypt", description="Link do transkryptu spotkania z danej daty")
    @app_commands.describe(data="Data spotkania: RRRR-MM-DD, DD.MM.RRRR, dzisiaj, wczoraj")
    @app_commands.checks.has_permissions(administrator=True)
    async def transkrypt(self, interaction: discord.Interaction, data: str):
        today_warsaw = discord.utils.utcnow().astimezone(WARSAW).date()
        d = parse_date_arg(data, today=today_warsaw)
        if d is None:
            await interaction.response.send_message(
                "⚠️ Nie rozpoznaję tej daty. Użyj `RRRR-MM-DD`, `DD.MM.RRRR`, "
                "`dzisiaj` albo `wczoraj`.",
                ephemeral=True,
            )
            return

        if not gdrive.is_configured():
            await interaction.response.send_message(
                "⚠️ Google Drive nie jest skonfigurowany.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            files = await asyncio.to_thread(gdrive.find_files, f"Lifehackerzy_{d.isoformat()}")
        except Exception as e:
            logger.error("Drive lookup failed for %s: %s", d.isoformat(), e)
            await interaction.followup.send(
                "❌ Wyszukiwanie na Google Drive nie powiodło się.", ephemeral=True
            )
            return

        meetings = _group_meetings(files)
        if not meetings:
            await interaction.followup.send(
                f"Brak nagrań z {d.isoformat()} na Drive.", ephemeral=True
            )
            return

        lines = []
        for (started, slug, _rec_id), entry in sorted(meetings.items(), key=lambda kv: kv[0][0]):
            time_str = started.strftime("%H:%M")
            audio = entry["audio"]
            md = entry["transcript_md"]
            txt = entry["transcript_txt"]
            parts = []
            if md is not None:
                parts.append(f"[📝 transkrypt]({md['webViewLink']})")
            elif txt is not None:
                parts.append(f"[📝 transkrypt (txt)]({txt['webViewLink']})")
            if audio is not None:
                parts.append(f"[🎙️ audio]({audio['webViewLink']})")
            if not parts:
                continue
            if md is None and txt is None:
                parts.append("(brak transkryptu)")
            lines.append(f"**{time_str}** #{slug} — " + " · ".join(parts))

        if not lines:
            await interaction.followup.send(
                f"Brak nagrań z {d.isoformat()} na Drive.", ephemeral=True
            )
            return

        await interaction.followup.send(
            f"**Nagrania z {d.isoformat()}:**\n" + "\n".join(lines), ephemeral=True
        )

    @transkrypt.error
    async def transkrypt_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            text = "⛔ Tylko dla administratora."
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
            return
        logger.error("admin transkrypt command error: %s", error)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminLookup(bot))
