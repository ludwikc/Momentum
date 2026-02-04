import discord
from discord.ext import commands

class prefixdone(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command()
    async def trening(self, ctx):
        await ctx.send(f"Hej {ctx.author.mention}, od teraz używamy **wyłącznie** nowocześniejszych komend `/done trening`, spróbuj raz jeszcze!")
        
    @commands.command()
    async def medytacja(self, ctx):
        await ctx.send(f"Hej {ctx.author.mention}, od teraz używamy **wyłącznie** nowocześniejszych komend `/done medytacja`, spróbuj raz jeszcze!")
        
    @commands.command(aliases=["sukces", "mit"])
    async def sumit(self, ctx):
        await ctx.send(f"Hej {ctx.author.mention}, od teraz używamy **wyłącznie** nowocześniejszych komend `/done sukces`, spróbuj raz jeszcze!")
        
    @commands.command()
    async def dziennik(self, ctx):
        await ctx.send(f"Hej {ctx.author.mention}, od teraz używamy **wyłącznie** nowocześniejszych komend `/done dziennik`, spróbuj raz jeszcze!")
        
    @commands.command(name="done")
    async def done_command(self, ctx, activity=None):
        await ctx.send(f"Hej {ctx.author.mention}, od teraz używamy **wyłącznie** slash komend `/done`. Proszę użyj polecenia zaczynającego się ukośnikiem `/` a nie wykrzyknikiem `!`")

async def setup(bot: commands.Bot):
    await bot.add_cog(prefixdone(bot))
