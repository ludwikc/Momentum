import discord
from discord.ext import commands
import os
import logging
import asyncio
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("momentum_bot")

# Load environment variables (alternatively, keep using private.py if preferred)
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("TKN")  # Fallback to TKN if using private.py

# Check if token is available
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN not found! Did you create a .env file?")

# Set up intents - only use what's needed
intents = discord.Intents.default()
intents.message_content = True  # For command processing
intents.members = True          # For member tracking
intents.voice_states = True     # For voice channel tracking
intents.guilds = True           # For server information

# Initialize the bot with both prefix and slash commands
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} servers")
    
    # Sync application commands
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler for Discord events."""
    logger.error(f"An error occurred in event {event}")
    
async def main():
    """Main entry point for the bot."""
    async with bot:
        # Load all extensions/cogs from the cogs directory
        initial_extensions = []
        
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                initial_extensions.append(f"cogs.{filename[:-3]}")
        
        for extension in initial_extensions:
            try:
                await bot.load_extension(extension)
                logger.info(f"Loaded extension {extension}")
            except Exception as e:
                logger.error(f"Failed to load extension {extension}: {e}")
                
        # Start the bot
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutdown by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
