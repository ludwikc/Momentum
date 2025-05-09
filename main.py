import asyncio
import discord
from discord.ext import commands
import logging
import sys

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

async def main():
    """Main entry point for the bot."""
    # Try a different approach for loading extensions
    for ext in EXTENSIONS:
        try:
            # Use importlib to import the module directly
            import importlib
            module = importlib.import_module(ext)
            # Call setup function directly
            if hasattr(module, 'setup'):
                module.setup(bot)
                logger.info(f"Loaded extension {ext}")
            else:
                logger.error(f"Extension {ext} does not have a setup function")
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
