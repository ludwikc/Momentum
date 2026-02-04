import discord
from discord import app_commands
from discord.ext import commands
from pymongo import MongoClient
from linkdb import link_db
from datetime import datetime
import logging
from config import ACTIVITIES as act

logger = logging.getLogger("momentum_bot.done")

class done(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        try:
            self.collection = MongoClient(link_db)["activity_db"]["activities"]
            logger.info("Connected to MongoDB")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            self.collection = None

    @app_commands.command(name="done", description="Zaloguj aktywność")
    @app_commands.describe(activity="Wybierz aktywność")
    @app_commands.choices(activity=[
        app_commands.Choice(name=f"{emoji} {name.capitalize()}", value=name)
        for name, emoji in act.items()
    ])
    async def done_command(self, interaction: discord.Interaction, activity: app_commands.Choice[str]):
        if not self.collection:
            await interaction.response.send_message("Przepraszam, baza danych jest niedostępna. Spróbuj później.", ephemeral=True)
            return

        activity_type = activity.value
        user_id = str(interaction.user.id)
        user_record = self.collection.find_one({"user_id": user_id})

        if not user_record:
            user_record = {
                "user_id": user_id,
                "streaks": {a: 0 for a in act},
                "last_reset": datetime.utcnow().strftime("%Y-%m-%d"),
            }
        else:
            user_record.setdefault("last_reset", datetime.utcnow().strftime("%Y-%m-%d"))

        today = datetime.utcnow()
        last_reset = datetime.strptime(user_record["last_reset"], "%Y-%m-%d")
        if today.month != last_reset.month:
            user_record["streaks"] = {a: 0 for a in act}
            user_record["last_reset"] = today.strftime("%Y-%m-%d")

        user_record["streaks"][activity_type] = user_record["streaks"].get(activity_type, 0) + 1
        self.collection.update_one(
            {"user_id": user_id}, {"$set": user_record}, upsert=True
        )

        embed = discord.Embed(title="Aktywność", color=0x280586)
        embed.add_field(
            name="",
            value=f"🔥 To {user_record['streaks'][activity_type]} {activity_type} w tym miesiącu!",
        )

        avatar = interaction.user.avatar or interaction.user.default_avatar
        embed.set_thumbnail(url=avatar.url)

        for name, streak_count in user_record["streaks"].items():
            embed.add_field(
                name=f"{act[name]} {name.capitalize()}: {streak_count}",
                value="",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(done(bot))
