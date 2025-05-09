import discord
from discord.ext import commands
from discord.commands import slash_command, Option
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

    @slash_command(name="pytanie", description="Zadaj pytanie botowi")
    async def pytanie(self, ctx, pytanie: Option(str, "Twoje pytanie", required=True)):
        """Odpowiada na często zadawane pytania"""
        pytanie = pytanie.lower().strip()
        
        # Check for exact matches
        if pytanie in self.qa_pairs:
            await ctx.respond(self.qa_pairs[pytanie])
            return
            
        # Check for partial matches
        for key, value in self.qa_pairs.items():
            if key in pytanie or any(word in pytanie for word in key.split()):
                await ctx.respond(value)
                return
                
        # No match found
        await ctx.respond("Nie znam odpowiedzi na to pytanie. Spróbuj zapytać o coś innego lub skontaktuj się z administratorem.")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for question marks in messages"""
        if message.author.bot:
            return
            
        content = message.content.lower().strip()
        if content.endswith("?"):
            # Check for matches in our QA database
            for key, value in self.qa_pairs.items():
                if key in content or any(word in content for word in key.split()):
                    await message.channel.send(value)
                    return

async def setup(bot: commands.Bot):
    await bot.add_cog(QACog(bot))
