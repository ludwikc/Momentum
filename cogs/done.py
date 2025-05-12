import discord
from pymongo import MongoClient
from discord.ext import commands
from linkdb import link_db
from datetime import datetime
from config import ACTIVITIES as act

mongo_client = MongoClient(link_db)
db = mongo_client["activity_db"]
collection = db["activities"]

class done(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.collection = MongoClient(link_db)["activity_db"]["activities"]

    @discord.slash_command(name="done", description=f'Lista aktywności: {", ".join(act)}')
    @discord.option(name="activity", description="Wybierz aktywność", choices=[
        discord.OptionChoice(name=f"{act_emoji} {act_type.capitalize()}", value=act_type)
        for act_type, act_emoji in act.items()
    ])
    async def done_command(
        self, 
        ctx, 
        activity: str = None
    ):
        user_id = str(ctx.author.id)
        user_record = collection.find_one({"user_id": user_id})

        if not user_record:
            user_record = {
                "user_id": user_id,
                "streaks": {act_type: 0 for act_type in act},
                "last_reset": datetime.utcnow().strftime("%Y-%m-%d"),
            }
        else:
            user_record.setdefault("last_reset", datetime.utcnow().strftime("%Y-%m-%d"))

        today = datetime.utcnow()
        last_reset = datetime.strptime(user_record["last_reset"], "%Y-%m-%d")
        if today.month != last_reset.month:
            user_record["streaks"] = {act_type: 0 for act_type in act}
            user_record["last_reset"] = today.strftime("%Y-%m-%d")

        # Extract activity type from the choice
        if activity:
            activity_type = activity
        else:
            await ctx.respond(
                f'Proszę wybrać aktywność. Dostępne aktywności: {", ".join(act)}'
            )
            return
            
        if activity_type in act:
            user_record["streaks"][activity_type] = (
                user_record["streaks"].get(activity_type, 0) + 1
            )
            collection.update_one(
                {"user_id": user_id}, {"$set": user_record}, upsert=True
            )

            embed = discord.Embed(title="Aktywność", color=0x280586)
            embed.add_field(
                name="",
                value=f"🔥 To {user_record['streaks'][activity_type]} {activity_type} w tym miesiącu!",
            )

            if ctx.author.avatar:
                embed.set_thumbnail(url=ctx.author.avatar.url)
            else:
                embed.set_thumbnail(url=ctx.author.default_avatar.url)

            for activity_type, streak_count in user_record["streaks"].items():
                emoji = act[activity_type]
                embed.add_field(
                    name=f"{emoji} {activity_type.capitalize()}" + f": {streak_count}",
                    value="",
                    inline=False,
                )
            await ctx.respond(embed=embed)

        else:
            await ctx.respond(
                f'Niepoprawna aktywność. By zacząć streak wybierz z podanych aktywności: {", ".join(act)}'
            )

def setup(bot: commands.Bot):
    bot.add_cog(done(bot))
