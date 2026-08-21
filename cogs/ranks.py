"""Rangi za czas na głosowych (StudyLion ranks port, voice-hours ladder).

Config-driven: VOICE_RANKS in config.py is a list of (hours, role_id,
reward_coins) thresholds over lifetime tracked voice hours. Empty list ⇒ the
cog stays dormant. On every voice flush (momentum_voice_flushed event from
voice_tracker) the member gets the highest qualifying rank role, other ladder
roles are removed (StudyLion award-highest/remove-others), the rank's coin
reward is minted once per threshold (user_rank_state guard), and the rank-up
is announced in the progress channel.
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging

from activity_embed import format_duration_pl
from config import COINS_EMOJI, RANKS_ANNOUNCE_CHANNEL_ID, VOICE_RANKS
from db import award_coins_safe, get_voice_stats, record_rank_award

logger = logging.getLogger("momentum_bot.ranks")


class Ranks(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ladder = sorted(VOICE_RANKS)  # (hours, role_id, reward) ascending
        logger.info(
            f"Ranks cog initialized ({len(self.ladder)} ranks configured)"
            if self.ladder
            else "Ranks cog initialized (dormant — VOICE_RANKS empty)"
        )

    def _deserved(self, hours: float):
        """Highest threshold ≤ lifetime hours, or None."""
        best = None
        for rank in self.ladder:
            if hours >= rank[0]:
                best = rank
        return best

    @commands.Cog.listener()
    async def on_momentum_voice_flushed(self, uid: int, total_seconds: int):
        if not self.ladder:
            return
        deserved = self._deserved(total_seconds / 3600)
        if deserved is None:
            return
        hours_req, role_id, reward = deserved

        for guild in self.bot.guilds:
            member = guild.get_member(uid)
            if member is None:
                continue
            role = guild.get_role(role_id)
            if role is None:
                logger.warning(f"VOICE_RANKS role {role_id} not found in {guild.id}")
                continue
            try:
                ladder_ids = {r[1] for r in self.ladder}
                to_remove = [
                    r for r in member.roles if r.id in ladder_ids and r.id != role_id
                ]
                if to_remove:
                    await member.remove_roles(
                        *to_remove, reason="Momentum: aktualizacja rangi głosowej"
                    )
                if role not in member.roles:
                    await member.add_roles(
                        role, reason=f"Momentum: ranga za {hours_req}h na głosowych"
                    )
            except discord.Forbidden:
                logger.warning(
                    f"Missing permissions to manage rank roles for {uid} in {guild.id}"
                )
                continue
            except Exception as e:
                logger.error(f"Rank role update failed for {uid}: {e}")
                continue

            # Coin reward + announcement exactly once per threshold.
            try:
                result = record_rank_award(str(uid), hours_req)
            except Exception as e:
                logger.error(f"record_rank_award failed for {uid}: {e}")
                continue
            if not result or not result.get("newly_awarded"):
                continue

            if reward > 0:
                award_coins_safe(
                    str(uid), reward, "rank", {"hours": hours_req, "role_id": str(role_id)}
                )
            channel = self.bot.get_channel(RANKS_ANNOUNCE_CHANNEL_ID)
            if channel:
                try:
                    msg = (
                        f"🏅 {member.mention} osiąga rangę **{role.name}** "
                        f"({hours_req}h na kanałach głosowych)!"
                    )
                    if reward > 0:
                        msg += f" (+{reward} {COINS_EMOJI})"
                    await channel.send(msg)
                except Exception as e:
                    logger.error(f"Rank announcement failed: {e}")

    @app_commands.command(
        name="rangi", description="Drabinka rang za czas na głosowych + Twój postęp"
    )
    async def rangi(self, interaction: discord.Interaction):
        if not self.ladder:
            await interaction.response.send_message(
                "Rangi nie są jeszcze skonfigurowane (VOICE_RANKS w config.py).",
                ephemeral=True,
            )
            return
        try:
            voice = get_voice_stats(str(interaction.user.id)) or {}
            total_seconds = voice.get("total_seconds", 0)
            hours = total_seconds / 3600

            embed = discord.Embed(title="🏅 Rangi głosowe", color=0x280586)
            lines = []
            for hours_req, role_id, reward in self.ladder:
                role = interaction.guild.get_role(role_id) if interaction.guild else None
                name = role.mention if role else f"(rola {role_id})"
                marker = "✅" if hours >= hours_req else "▫️"
                line = f"{marker} **{hours_req}h** — {name}"
                if reward > 0:
                    line += f" (+{reward} {COINS_EMOJI})"
                lines.append(line)
            embed.description = "\n".join(lines)

            next_rank = next((r for r in self.ladder if hours < r[0]), None)
            footer = f"Twój czas: {format_duration_pl(total_seconds)}"
            if next_rank:
                remaining = int(next_rank[0] * 3600 - total_seconds)
                footer += f" · do następnej rangi: {format_duration_pl(remaining)}"
            embed.set_footer(text=footer)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in /rangi: {e}")
            await interaction.response.send_message(
                "Wystąpił błąd podczas pobierania rang. Spróbuj ponownie później.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Ranks(bot))
