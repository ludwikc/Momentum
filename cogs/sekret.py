    import discord
    from discord.ext import commands
    from discord import app_commands
    import config
    import logging

    logger = logging.getLogger("momentum_bot")

    class Sekret(commands.Cog):
        def __init__(self, bot: commands.Bot):
            self.bot = bot
            
        @app_commands.command(
            name="sekret",
            description="Wyślij anonimową wiadomość na kanał sekretów"
        )
        @app_commands.describe(message="Treść sekretu do udostępnienia")
        async def sekret(self, interaction: discord.Interaction, message: str):
            # Check if command is used in the correct channel
            if interaction.channel_id != config.SEKRET_CHANNEL_ID:
                await interaction.response.send_message(
                    "Ta komenda działa tylko na kanale sekretów.",
                    ephemeral=True
                )
                return
                
            # Validate message content
            if not message or len(message) > 1900:  # Leave room for the template text
                await interaction.response.send_message(
                    "Treść sekretu nie może być pusta ani przekraczać 1900 znaków.",
                    ephemeral=True
                )
                return
                
            try:
                # Acknowledge the command with an ephemeral message
                await interaction.response.send_message(
                    "Twój sekret został opublikowany anonimowo.",
                    ephemeral=True
                )
                
                # Format and send the anonymous message
                formatted_message = f"Lifehacker podzielił się właśnie sekretem: || {message} ||"
                
                # Get the channel object
                channel = self.bot.get_channel(config.SEKRET_CHANNEL_ID)
                if channel:
                    await channel.send(formatted_message)
                else:
                    logger.error(f"Could not find channel with ID {config.SEKRET_CHANNEL_ID}")
                    
            except Exception as e:
                logger.error(f"Error in sekret command: {e}")
                # Try to notify the user if the response hasn't been sent yet
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Wystąpił błąd podczas przetwarzania twojego sekretu.",
                        ephemeral=True
                    )

    async def setup(bot: commands.Bot):
        await bot.add_cog(Sekret(bot))
