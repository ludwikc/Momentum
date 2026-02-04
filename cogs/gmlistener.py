import discord
from discord.ext import commands
from pymongo import MongoClient
from datetime import datetime, timedelta
from linkdb import link_db
import random
from emoji import *
import pytz
from random_msg import random_message
import logging
import re
from config import MORNING_GREETING_START_HOUR, MORNING_GREETING_END_HOUR

logger = logging.getLogger("momentum_bot.gmlistener")

class GMListener(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        try:
            self.mongo_client = MongoClient(link_db)
            self.collection = self.mongo_client["wakeup_db"]["wake_ups"]
            logger.info("Connected to MongoDB")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            self.mongo_client = None
            self.collection = None
        
        self.polish_timezone = pytz.timezone("Europe/Warsaw")
        
    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("GMListener cog is ready")
        
    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignore bot messages
        if message.author.bot:
            return
            
        try:
            # Check if message contains "gm" or "dzień dobry" (case insensitive)
            content = message.content.lower()
            if re.search(r'\bgm\b', content) or "dzień dobry" in content:
                if not self.collection:
                    logger.error("MongoDB collection not available")
                    await message.channel.send("Przepraszam, nie mogę teraz przetworzyć tego polecenia. Spróbuj ponownie później.")
                    return
                    
                user_id = str(message.author.id)
                user_record = self.collection.find_one({"user_id": user_id})

                current_time_polish = datetime.now(self.polish_timezone)
                start_time = current_time_polish.replace(
                    hour=MORNING_GREETING_START_HOUR, minute=0, second=0, microsecond=0
                )
                end_time = current_time_polish.replace(
                    hour=MORNING_GREETING_END_HOUR, minute=0, second=0, microsecond=0
                )
                
                # Convert previous_wakeup string to datetime if it exists
                previous_wakeup = None
                if user_record and "last_wakeup" in user_record:
                    if isinstance(user_record["last_wakeup"], str):
                        try:
                            previous_wakeup = datetime.fromisoformat(user_record["last_wakeup"])
                        except ValueError:
                            previous_wakeup = current_time_polish - timedelta(days=1)
                    else:
                        previous_wakeup = user_record["last_wakeup"]
                else:
                    previous_wakeup = current_time_polish - timedelta(days=1)
                    
                if user_record:
                    streak_momentum = user_record.get("streak_momentum", 0)
                    streak_wakeups = user_record.get("streak_wakeups", 0)
                else:
                    streak_momentum = 0
                    streak_wakeups = 0

                # Check if already woke up today
                if previous_wakeup and current_time_polish.date() == previous_wakeup.date():
                    await message.channel.send(f"{message.author.mention} Za mało kawy? Tylko raz można się obudzić ☕️")
                    return

                # Process early morning greeting (4-6 AM by default)
                if start_time < current_time_polish < end_time:
                    streak_wakeups += 1
                    streak_momentum += 1
                    
                    # Apply emoji based on momentum
                    emoji_to_use = momentum_emoji if 'momentum_emoji' in globals() else "🔥"
                    
                    reply_message = (
                        f"🌅 **Dzień dobry {message.author.mention}!** "
                        + random.choice(random_message)
                        + f" To twoja {streak_wakeups} pobudka z samego rana :raised_hands:! "
                        + f"Twoje momentum wynosi {streak_momentum} {emoji_to_use}!"
                    )
                else:
                    # Outside of early morning hours - reset momentum
                    streak_momentum = 0
                    reply_message = (
                        f"🌅 **Dzień dobry {message.author.mention}!** "
                        + random.choice(random_message)
                        + " :raised_hands:"
                    )

                # Update database record
                try:
                    self.collection.update_one(
                        {"user_id": user_id},
                        {
                            "$set": {
                                "last_wakeup": current_time_polish,
                                "streak_wakeups": streak_wakeups,
                                "streak_momentum": streak_momentum,
                            }
                        },
                        upsert=True,
                    )
                except Exception as e:
                    logger.error(f"Failed to update database: {e}")

                await message.channel.send(reply_message)
        except Exception as e:
            logger.error(f"Error in on_message: {e}")
            import traceback
            traceback.print_exc()

async def setup(bot: commands.Bot):
    await bot.add_cog(GMListener(bot))
