"""Owner-only /momentum-reboot slash command.

Lets the owner restart the bot from Discord (e.g. to pick up new code or recover
from a wedged state) without shell access.

Restart mechanism: ``os.execv`` replaces the current process image with a fresh
interpreter running the same entrypoint. This is independent of the systemd
``Restart=`` policy (the unit uses ``on-failure``, so a clean exit would NOT be
restarted) — execv keeps the same PID, so systemd keeps tracking the service, and
the Discord gateway socket is closed-on-exec, so the old connection drops cleanly
and the fresh process reconnects.
"""
import asyncio
import logging
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands

from config import MOMENTUM_OWNER_ID

logger = logging.getLogger("momentum_bot.reboot")


class Reboot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("Reboot cog initialized")

    @app_commands.command(
        name="momentum-reboot",
        description="Restartuje bota Momentum (tylko właściciel).",
    )
    async def momentum_reboot(self, interaction: discord.Interaction):
        if interaction.user.id != MOMENTUM_OWNER_ID:
            await interaction.response.send_message(
                "⛔ Tylko właściciel może restartować Momentum.", ephemeral=True
            )
            return

        await interaction.response.send_message("♻️ Restartuję Momentum… wrócę za chwilę.")
        logger.info("Reboot requested by owner %s — re-execing process", interaction.user.id)
        # Let the HTTP response flush to Discord before we replace the process.
        await asyncio.sleep(1.0)
        try:
            os.execv(sys.executable, [sys.executable, *sys.argv])
        except Exception as e:
            # execv only returns if it failed — surface it and stay up.
            logger.error("os.execv failed, bot NOT restarted: %s", e)
            try:
                await interaction.followup.send(f"⚠️ Restart się nie powiódł: {e}")
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Reboot(bot))
