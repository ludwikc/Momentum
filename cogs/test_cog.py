import discord
from discord.ext import commands

class TestCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    @commands.command()
    async def hello(self, ctx):
        await ctx.send("Hello, world!")

async def setup(bot: commands.Bot):
    await bot.add_cog(TestCog(bot))
