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

# Set up intents - only use what's needed
intents = discord.Intents.default()
intents.message_content = True  # For command processing
intents.members = True          # For member tracking
intents.voice_states = False    # Disable voice channel tracking to avoid audioop dependency
intents.guilds = True           # For server information

# Initialize the bot with prefix commands only (no slash commands for now)
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} servers")
    
    # We're not using slash commands for now, so we'll skip syncing
    # try:
    #     synced = await bot.tree.sync()
    #     logger.info(f"Synced {len(synced)} command(s)")
    # except Exception as e:
    #     logger.error(f"Failed to sync commands: {e}")

@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler for Discord events."""
    logger.error(f"An error occurred in event {event}")
    import traceback
    traceback.print_exc()

# List of extensions to load
EXTENSIONS = [
    "cogs.test_cog",
    # "cogs.sekret",  # Commented out due to AppCommandOptionType error
    "cogs.gmlistener",
    "cogs.gm",
    "cogs.dailyreminder",
    # "cogs.qacog",  # Commented out due to AppCommandOptionType error
    "cogs.auto_assign_role",
    # "cogs.queue_cog",  # Commented out due to AppCommandOptionType error
    "cogs.prefixdone",
    # "cogs.leaderboard",  # Commented out due to AppCommandOptionType error
    # "cogs.done",  # Commented out due to AppCommandOptionType error
]

# Simple function to load extensions
def load_extensions():
    for ext in EXTENSIONS:
        try:
            bot.load_extension(ext)
            logger.info(f"Loaded extension {ext}")
        except Exception as e:
            logger.error(f"Failed to load extension {ext}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    try:
        # Load all extensions
        load_extensions()
        
        # Run the bot
        logger.info("Starting bot...")
        bot.run(DISCORD_TOKEN)
    except KeyboardInterrupt:
        logger.info("Bot shutdown by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
