import discord
from discord.ext import commands
import os
from private import *

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

invites = {}


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


initial_extensions = []

for filename in os.listdir("./cogs"):
    if filename.endswith(".py"):
        initial_extensions.append("cogs." + filename[:-3])

if __name__ == "__main__":
    for extension in initial_extensions:
        bot.load_extension(extension)

bot.run(TKN)
