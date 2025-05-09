import asyncio
import discord
from discord.ext import commands
import logging
import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# Try to get token from environment variables first, then from private.py as fallback
try:
    from private import DISCORD_TOKEN
except (ImportError, AttributeError):
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

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

# Check if token is available
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing! Please set it in private.py or as an environment variable.")

# Set up intents - only use what's needed
intents = discord.Intents.default()
intents.message_content = True  # For command processing
intents.members = True          # For member tracking
intents.voice_states = False    # Disable voice channel tracking to avoid audioop dependency
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

# List of extensions to load
EXTENSIONS = [
    "cogs.sekret",
    "cogs.gmlistener",
    "cogs.gm",
    "cogs.dailyreminder",
    "cogs.qacog",
    "cogs.auto_assign_role",
    "cogs.queue_cog",
    "cogs.prefixdone",
    "cogs.leaderboard",
    "cogs.done",
]

async def main():
    """Main entry point for the bot."""
    for ext in EXTENSIONS:
        try:
            await bot.load_extension(ext)
            logger.info(f"Loaded extension {ext}")
        except Exception as e:
            logger.error(f"Failed to load extension {ext}: {e}")
    
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutdown by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
