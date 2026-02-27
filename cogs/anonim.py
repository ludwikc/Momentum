import discord
from discord.ext import commands
from discord import app_commands
import logging

logger = logging.getLogger("momentum_bot")

class Anonim(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("Anonim cog initialized")

    @app_commands.command(
        name="anonim",
        description="Wyślij anonimową wiadomość na tym kanale"
    )
    @app_commands.describe(message="Treść anonimowej wiadomości")
    async def anonim(self, interaction: discord.Interaction, message: str):
        # Validate message content
        if not message or len(message) > 1900:  # Leave room for the template text
            await interaction.response.send_message(
                "Treść wiadomości nie może być pusta ani przekraczać 1900 znaków.",
                ephemeral=True
            )
            return

        try:
            # Acknowledge the command with an ephemeral message
            await interaction.response.send_message(
                "Twoja anonimowa wiadomość została opublikowana.",
                ephemeral=True
            )

            # Format and send the anonymous message
            formatted_message = f"Wiadomość anonimowa: || {message} ||"

            # Send to the same channel where the command was used
            await interaction.channel.send(formatted_message)

        except Exception as e:
            logger.error(f"Error in anonim command: {e}")
            # Try to notify the user if the response hasn't been sent yet
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Wystąpił błąd podczas przetwarzania twojej wiadomości.",
                    ephemeral=True
                )

async def setup(bot: commands.Bot):
    await bot.add_cog(Anonim(bot))
