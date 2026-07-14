"""Profil — /profil (StudyLion student-profile-card port, embed edition).

The identity view: custom self-description tags (StudyLion's profile badges,
max PROFILE_MAX_TAGS × PROFILE_TAG_MAX_LEN chars) plus the headline numbers
(rank, monety, voice time, GM momentum). Numbers-heavy detail stays in
/statystyki. Viewing your own profile attaches an "Edytuj tagi" button that
opens a modal (StudyLion's Edit Profile Badges flow).
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging

from activity_embed import format_duration_pl
from config import (
    COINS_EMOJI,
    PROFILE_MAX_TAGS,
    PROFILE_TAG_MAX_LEN,
    VOICE_RANKS,
)
from db import get_user_activity_stats, profile_set_tags
from parsers import parse_profile_tags

logger = logging.getLogger("momentum_bot.profil")

DB_ERROR_MSG = "Wystąpił błąd bazy danych. Spróbuj ponownie później."


def _build_profile_embed(member: discord.Member, stats: dict) -> discord.Embed:
    embed = discord.Embed(title=f"👤 Profil — {member.display_name}", color=0x280586)
    avatar = member.avatar or member.default_avatar
    embed.set_thumbnail(url=avatar.url)

    tags = stats.get("profile_tags") or []
    if tags:
        embed.add_field(name="🏷️ Tagi", value=" · ".join(tags), inline=False)
    else:
        embed.add_field(
            name="🏷️ Tagi",
            value="*brak — opowiedz, czym się zajmujesz!*",
            inline=False,
        )

    # Rank line (only when the ladder is configured).
    voice_seconds = stats.get("voice_seconds_total", 0)
    if VOICE_RANKS:
        ladder = sorted(VOICE_RANKS)
        hours = voice_seconds / 3600
        current = None
        for rank in ladder:
            if hours >= rank[0]:
                current = rank
        nxt = next((r for r in ladder if hours < r[0]), None)
        if current and member.guild:
            role = member.guild.get_role(current[1])
            if role:
                embed.add_field(name=f"🏅 Ranga: {role.name}", value="", inline=False)
        if nxt:
            remaining = int(nxt[0] * 3600 - voice_seconds)
            embed.add_field(
                name=f"⏫ Do następnej rangi: {format_duration_pl(remaining)}",
                value="",
                inline=False,
            )

    if voice_seconds > 0:
        embed.add_field(
            name=f"🎙️ Na głosowych: {format_duration_pl(voice_seconds)}",
            value="",
            inline=False,
        )
    coins = stats.get("coins", 0)
    if coins > 0:
        embed.add_field(name=f"{COINS_EMOJI} Monety: {coins}", value="", inline=False)
    gm_momentum = stats.get("gm_momentum", 0)
    if gm_momentum > 0:
        embed.add_field(name=f"☀️ Momentum GM: {gm_momentum}", value="", inline=False)

    embed.set_footer(text="Pełne liczby: /statystyki")
    return embed


class TagsModal(discord.ui.Modal, title="Edytuj tagi profilu"):
    def __init__(self, cog: "Profil", member: discord.Member, current: list[str]):
        super().__init__(timeout=300)
        self.cog = cog
        self.member = member
        self.tags_input = discord.ui.TextInput(
            label=f"Tagi (max {PROFILE_MAX_TAGS}, rozdziel średnikiem)",
            placeholder="np. Programowanie; Bieganie; Stoicyzm",
            default="; ".join(current),
            required=False,
            max_length=(PROFILE_TAG_MAX_LEN + 2) * PROFILE_MAX_TAGS,
        )
        self.add_item(self.tags_input)

    async def on_submit(self, interaction: discord.Interaction):
        tags = parse_profile_tags(
            self.tags_input.value, PROFILE_MAX_TAGS, PROFILE_TAG_MAX_LEN
        )
        if tags is None:
            await interaction.response.send_message(
                f"Maksymalnie {PROFILE_MAX_TAGS} tagów po {PROFILE_TAG_MAX_LEN} "
                f"znaków (rozdziel średnikiem).",
                ephemeral=True,
            )
            return
        try:
            result = profile_set_tags(str(self.member.id), tags)
            if not result or not result.get("ok"):
                await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)
                return
            stats = get_user_activity_stats(str(self.member.id)) or {}
            embed = _build_profile_embed(self.member, stats)
            try:
                await interaction.response.edit_message(embed=embed)
            except Exception:
                await interaction.response.send_message(
                    "🏷️ Tagi zapisane!", ephemeral=True
                )
        except Exception as e:
            logger.error(f"Error saving profile tags: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)


class ProfilView(discord.ui.View):
    """Self-view only: the Edytuj tagi button (author-locked)."""

    def __init__(self, cog: "Profil", member: discord.Member, tags: list[str]):
        super().__init__(timeout=300)
        self.cog = cog
        self.member = member
        self.tags = tags
        self.message: discord.Message | None = None

    @discord.ui.button(label="Edytuj tagi", emoji="✏️", style=discord.ButtonStyle.secondary)
    async def edit_tags(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            await interaction.response.send_message(
                "To nie Twój profil — zobacz swój przez /profil. 😉", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            TagsModal(self.cog, self.member, self.tags)
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class Profil(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("Profil cog initialized")

    @app_commands.command(
        name="profil", description="Karta profilu (tagi, ranga, monety)"
    )
    @app_commands.describe(uzytkownik="Czyj profil pokazać (domyślnie Twój)")
    @app_commands.guild_only()
    async def profil(
        self,
        interaction: discord.Interaction,
        uzytkownik: discord.Member | None = None,
    ):
        member = uzytkownik or interaction.user
        if member.bot:
            await interaction.response.send_message(
                "Boty nie mają profili. 🤖", ephemeral=True
            )
            return
        try:
            stats = get_user_activity_stats(str(member.id)) or {}
            embed = _build_profile_embed(member, stats)
            if member.id == interaction.user.id:
                view = ProfilView(self, member, stats.get("profile_tags") or [])
                await interaction.response.send_message(embed=embed, view=view)
                view.message = await interaction.original_response()
            else:
                await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"Error in /profil: {e}")
            await interaction.response.send_message(
                "Wystąpił błąd podczas pobierania profilu. Spróbuj ponownie później.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Profil(bot))
