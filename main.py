import discord
from discord.ext import commands
import os
from private import *

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}!")

async def reload_extension(ctx, extension):
    try:
        bot.reload_extension(extension)
        await ctx.send(f"Reloaded extension: {extension}")
    except Exception as e:
        await ctx.send(f"Failed to reload extension {extension}: {e}")
        
@bot.command()
async def reload(ctx):
    if ctx.author.id == 294888996243243009:
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                extension = f"cogs.{filename[:-3]}"
                await reload_extension(ctx, extension)

initial_extensions = []
    
for filename in os.listdir('./cogs'):
    if filename.endswith('.py'):
        initial_extensions.append("cogs." + filename[:-3])
            
if __name__ == '__main__':
    for extension in initial_extensions:
        bot.load_extension(extension)
            
bot.run(TKN)