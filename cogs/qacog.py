import discord
from discord.ext import commands
from discord import app_commands
import logging

logger = logging.getLogger("momentum_bot.qacog")

class QACog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.qa_pairs = {
            "co to jest momentum": "Momentum to zasada, że utrzymanie regularności w działaniu prowadzi do lepszych wyników niż sporadyczne zrywy.",
            "jak działa bot": "Jestem botem Momentum, który pomaga śledzić codzienne aktywności, przypomina o spotkaniach i wspiera w budowaniu nawyków.",
            "kiedy spotkanie": "Codzienne spotkanie odbywa się o 12:34. Nie spóźnij się!",
            "jak dołączyć do kolejki": "Użyj komendy `/kolejka` aby dołączyć do kolejki mówiących.",
            "jak zgłosić sekret": "Użyj komendy `/sekret` na kanale sekretów, aby anonimowo podzielić się swoim sekretem."
        }
        logger.info("QACog initialized")

    @app_commands.command(name="pytanie", description="Zadaj pytanie botowi")
    @app_commands.describe(pytanie="Treść pytania")
    async def pytanie(self, interaction: discord.Interaction, pytanie: str):
        """Odpowiada na często zadawane pytania"""
        pytanie_lower = pytanie.lower().strip()

        # Check for exact matches
        if pytanie_lower in self.qa_pairs:
            await interaction.response.send_message(self.qa_pairs[pytanie_lower])
            return

        # Check for partial matches
        for key, value in self.qa_pairs.items():
            if key in pytanie_lower or any(word in pytanie_lower for word in key.split()):
                await interaction.response.send_message(value)
                return

        # No match found
        await interaction.response.send_message("Nie znam odpowiedzi na to pytanie. Spróbuj zapytać o coś innego lub skontaktuj się z administratorem.")

async def setup(bot: commands.Bot):
    await bot.add_cog(QACog(bot))
