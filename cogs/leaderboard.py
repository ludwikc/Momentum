import discord
from pymongo import MongoClient
from discord.ext import commands
from discord import app_commands
from discord import Embed
from emoji import *
from linkdb import link_db
from images import thumbnail
import logging

logger = logging.getLogger("momentum_bot.leaderboard")

mongo_client = MongoClient(link_db)
db = mongo_client["activity_db"]
collection = db["activities"]

act = {"trening": "💪", "medytacja": "🧘", "sukces": "💎", "dziennik": "📝"}

class leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.collection = MongoClient(link_db)["activity_db"]["activities"]

    @app_commands.command(
        name="leaderboard",
        description=f'Pokaż leaderboard dla wybranej aktywności: {", ".join(act)}'
    )
    async def leaderboard_command(
        self, 
        ctx, 
        activity: str
    ):
        # Extract activity type from the choice
        activity = activity.split()[1].lower()
        
        if activity not in act:
            await ctx.respond(
                f'Niepoprawna aktywność. Dostępne aktywności: {", ".join(act)}'
            )
            return

        try:
            # Find all users with the activity and sort them
            cursor = collection.find(
                {"streaks": {"$exists": True}},
                {f"streaks.{activity}": 1, "user_id": 1, "_id": 0}
            )
            
            # Filter out entries that don't have the activity
            entries = []
            for entry in cursor:
                if "streaks" in entry and activity in entry["streaks"]:
                    entries.append(entry)
            
            # Sort entries by the streak count
            sorted_entries = sorted(
                entries, 
                key=lambda x: x["streaks"][activity] if activity in x["streaks"] else 0,
                reverse=True
            )[:10]
            
            emoji = act[activity]

            embed = Embed(
                title=f"🏆 Leaderboard dla {activity.capitalize()} {emoji}", 
                color=0x280586
            )
            
            if not sorted_entries:
                embed.add_field(
                    name="Brak wyników",
                    value="Nikt jeszcze nie zaczął tej aktywności!",
                    inline=False
                )
            else:
                for index, entry in enumerate(sorted_entries):
                    try:
                        user = await self.bot.fetch_user(int(entry["user_id"]))
                        streak_count = entry["streaks"][activity]
                        embed.add_field(
                            name=f"{index+1}. {user.display_name}",
                            value=f"🔥 Total: {streak_count}",
                            inline=False
                        )
                    except Exception as e:
                        logger.error(f"Error fetching user {entry['user_id']}: {e}")
                        continue
            
            embed.set_thumbnail(url=thumbnail)
            await ctx.respond(embed=embed)
            
        except Exception as e:
            logger.error(f"Error generating leaderboard: {e}")
            await ctx.respond("Wystąpił błąd podczas generowania rankingu. Spróbuj ponownie później.")

async def setup(bot: commands.Bot):
    await bot.add_cog(leaderboard(bot))
