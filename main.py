from dotenv import load_dotenv
load_dotenv()

import asyncio
import discord
from discord.ext import commands
import logging
import sys
import os

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

# Set up asyncio debug if needed
if os.environ.get('DEBUG_ASYNCIO'):
    logger.info("Enabling asyncio debug mode")
    asyncio.get_event_loop().set_debug(True)

# Import the token from private.py
try:
    from private import DISCORD_TOKEN, validate_token
    
    # For testing purposes, we'll bypass token validation
    # is_valid, message = validate_token(DISCORD_TOKEN)
    # if not is_valid:
    #     logger.error(f"Discord token validation failed: {message}")
    #     logger.error("Please update the token in private.py with a valid Discord bot token.")
    #     sys.exit(1)
    
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN is missing! Please set it in private.py.")
        sys.exit(1)
        
except ImportError:
    logger.error("Failed to import from private.py. Make sure the file exists and contains DISCORD_TOKEN.")
    sys.exit(1)
except Exception as e:
    logger.error(f"Error while importing or validating token: {e}")
    sys.exit(1)

# Check if Python version is 3.8 or higher
import sys
if sys.version_info < (3, 8):
    logger.error("Python 3.8 or higher is required to run this bot.")
    sys.exit(1)

# Set up intents - only use what's needed
intents = discord.Intents.default()
intents.message_content = True  # For command processing
intents.members = True          # For member tracking
intents.voice_states = True     # Enable voice channel tracking for queue_cog
intents.guilds = True           # For server information

# Status notification channel
STATUS_CHANNEL_ID = 1015575570760880168
OWNER_USER_ID = 404038151565213696

# Initialize the bot with both prefix and slash commands
bot = commands.Bot(command_prefix="!", intents=intents)

async def notify_status(message: str):
    """Send a status notification to the admin channel."""
    try:
        channel = bot.get_channel(STATUS_CHANNEL_ID)
        if channel:
            await channel.send(f"<@{OWNER_USER_ID}> {message}")
    except Exception as e:
        logger.error(f"Failed to send status notification: {e}")

@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} servers")

    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} commands")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

    await notify_status("Bot Momentum jest online.")

@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler for Discord events."""
    logger.error(f"An error occurred in event {event}")
    import traceback
    traceback.print_exc()

# List of extensions to load
EXTENSIONS = [
    "cogs.test_cog",
    "cogs.gmlistener",
    "cogs.gm",
    "cogs.dailyreminder",
    "cogs.auto_assign_role",
    "cogs.prefixdone",
    "cogs.done",
    "cogs.leaderboard",  # Activity leaderboards
    "cogs.sekret",
    "cogs.anonim",
    "cogs.qacog",
    "cogs.queue_cog",
    "cogs.thread_notify",
]

# Function to load extensions
async def load_extensions():
    for ext in EXTENSIONS:
        try:
            await bot.load_extension(ext)
            logger.info(f"Loaded extension {ext}")
        except Exception as e:
            logger.error(f"Failed to load extension {ext}: {e}")
            import traceback
            traceback.print_exc()

async def shutdown():
    """Send offline notification and close the bot gracefully."""
    await notify_status("Bot Momentum przechodzi w tryb offline.")
    await bot.close()

if __name__ == "__main__":
    try:
        async def main():
            await load_extensions()
            logger.info("Starting bot...")

            # Register signal handlers for graceful shutdown
            import signal
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.ensure_future(shutdown()))

            await bot.start(DISCORD_TOKEN)

        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutdown by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
