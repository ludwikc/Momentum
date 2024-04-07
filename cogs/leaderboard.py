import discord
from pymongo import MongoClient
from discord.ext import commands
from discord import Embed
from emoji import *
from linkdb import link_db
from images import thumbnail

mongo_client = MongoClient(link_db)
db = mongo_client["activity_db"]
collection = db["activities"]

act = {'trening': '💪', 'medytacja': '🧘', 'sukces': '💎'}

class leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.collection = MongoClient(link_db)['activity_db']['activities']
        
    @discord.slash_command(description=f'Pokaż leaderboard dla wybranej aktywności: {", ".join(act)}')
    async def leaderboard(self, ctx, activity: str):
        activity = activity.lower()
        if activity not in act:
            await ctx.respond(f'Niepoprawna aktywność. Dostępne aktywności: {", ".join(act)}')
            return
        
        leaderboard = collection.find({}, {f'streaks.{activity}': 1, 'user_id': 1, '_id': 0}).sort(f'streaks.activity', -1)
        sorted_leaderboard = sorted(leaderboard, key=lambda x: x['streaks'][activity], reverse=True)[:10]
        emoji = act[activity]
        
        embed = Embed(title=f"🏆 Leaderboard dla {activity.capitalize()} {emoji}", color=0x280586)
        for index, entry in enumerate(sorted_leaderboard):
            user = await self.bot.fetch_user(entry['user_id'])
            streak_count = entry['streaks'][activity]
            embed.add_field(name=f"{index+1}. {user.display_name}",
                            value=f"🔥 Total: {streak_count}",
                            inline=False
                            )
            embed.set_thumbnail(url=thumbnail)
            
        await ctx.respond(embed=embed)
        
def setup(bot:commands.Bot):
    bot.add_cog(leaderboard(bot))