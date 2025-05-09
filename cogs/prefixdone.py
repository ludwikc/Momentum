import discord
from pymongo import MongoClient
from discord.ext import commands
from linkdb import link_db

class prefixdone(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command()
    async def trening(self, ctx):
        await ctx.send(f"Hej {ctx.author.mention}, od teraz używamy nowocześniejszych komend `/done trening`, spróbuj raz jeszcze!")
        
    @commands.command()
    async def medytacja(self, ctx):
        await ctx.send(f"Hej {ctx.author.mention}, od teraz używamy nowocześniejszych komend `/done medytacja`, spróbuj raz jeszcze!")
        
    @commands.command(aliases=["sukces", "mit"])
    async def sumit(self, ctx):
        await ctx.send(f"Hej {ctx.author.mention}, od teraz używamy nowocześniejszych komend `/done sukces`, spróbuj raz jeszcze!")
        
    @commands.command()
    async def dziennik(self, ctx):
        await ctx.send(f"Hej {ctx.author.mention}, od teraz używamy nowocześniejszych komend `/done dziennik`, spróbuj raz jeszcze!")

def setup(bot: commands.Bot):
    bot.add_cog(prefixdone(bot))
