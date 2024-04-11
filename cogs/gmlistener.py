import discord
from discord.ext import commands
from pymongo import MongoClient
import pytz
from datetime import datetime, timedelta
from linkdb import link_db
from emoji import *
from random_msg import random_message
import random

mongo_client = MongoClient(link_db)
db = mongo_client["wakeup_db"]
collection = db["wake_ups"]

class gmlistener(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.collection = MongoClient(link_db)["wakeup_db"]["wake_ups"]
        self.polish_timezone = pytz.timezone(
            "Europe/Warsaw"
        )  # Set the correct timezone
        
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return
            
        if "gm".lower() in message.content.lower():
            user_id = str(message.author.id)
            user_record = self.collection.find_one({"user_id": user_id})

            current_time_polish = datetime.now(self.polish_timezone)
            start_time = current_time_polish.replace(hour=4, minute=0, second=0, microsecond=0)
            end_time = current_time_polish.replace(hour=6, minute=0, second=0, microsecond=0)
            previous_wakeup = (
                user_record["last_wakeup"]
                if user_record
                else current_time_polish - timedelta(days=1)
            )
            
            if user_record:
                streak_momentum = user_record.get("streak_momentum")
                streak_wakeups = user_record.get("streak_wakeups")
            else:
                streak_momentum = 0
                streak_wakeups = 0
                
            if current_time_polish.date() == previous_wakeup.date():
                await message.channel.send("Za mało kawy? Tylko raz można się obudzić ☕️")
                return
            
            if start_time < current_time_polish < end_time:
                if streak_wakeups >= 0:
                    streak_wakeups += 1
                
                if streak_momentum >= 0:
                    streak_momentum += 1
                    reply_message = (
                        f"🌅 **Dzień dobry {message.author.mention}!** "
                        + random.choice(random_message)
                        + f" To twoja {streak_wakeups} pobudka z samego rana :raised_hands:! Twoje momentum wynosi {streak_momentum} {momentum_emoji}!"
                    )
                else:
                    streak_wakeups += 1
                    streak_momentum += 1
                    reply_message = (
                        f"🌅 **Dzień dobry {message.author.mention}!** "
                        + random.choice(random_message)
                        + f" To twoja {streak_wakeups} pobudka z samego rana :raised_hands:! Twoje momentum wynosi {streak_momentum} {momentum_emoji}!"
                    )

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
                updated_record = self.collection.find_one({"user_id": user_id})
                streak_wakeups = updated_record["streak_wakeups"]
            
            else:
                streak_momentum = 0
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
                reply_message = f"🌅 **Dzień dobry {message.author.mention}!** " + random.choice(random_message) + " :raised_hands:"

            await message.channel.send(reply_message)
            
def setup(bot: commands.Bot):
    bot.add_cog(gmlistener(bot))