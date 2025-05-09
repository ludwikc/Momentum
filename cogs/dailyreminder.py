import discord
from discord.ext import commands, tasks
import datetime
import pytz
import logging

logger = logging.getLogger("momentum_bot.daily_reminder")

CHANNEL_ID = 1120658406160732160  # Target text channel ID

class DailyReminderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.polish_timezone = pytz.timezone("Europe/Warsaw")  # Ensure correct timezone
        self.schedule_reminders.start()  # Start the reminder loop

    def cog_unload(self):
        self.schedule_reminders.cancel()  # Stop the task when the cog is unloaded

    async def send_reminder(self, message: str):
        """Helper function to send a reminder message to the specified channel."""
        channel = self.bot.get_channel(CHANNEL_ID)
        if channel:
            await channel.send(message)
            logger.info(f"Sent reminder at {datetime.datetime.now(self.polish_timezone).strftime('%H:%M')}")
        else:
            logger.error(f"Channel {CHANNEL_ID} not found!")

    @tasks.loop(minutes=1)
    async def schedule_reminders(self):
        """Checks the current time every minute and sends reminders at specific times."""
        now = datetime.datetime.now(self.polish_timezone).strftime("%H:%M")
        reminders = {
            "12:34": "🕧 Witajcie na dzisiejszej sesji 12:34 Daily Coaching. <@272937604339466240> będzie nagrywać nasze spotkanie, aby potem je podsumować na Platformie. A więc bez zbędnych wstępów - zaczynajmy: co mogę dziś dla Was zrobić?",
            "12:45": "Tak tylko przypominam, że zostało nam ~14 minut spotkania.",
            "12:54": "⏰ Kończymy za ~5 minut.",
            "12:59": "🕐 12:59, pora wracać do stawiania czoła swoim wyzwaniom! Dziękuję za dziś i widzimy się jutro o 12:34!"
        }

        if now in reminders:
            await self.send_reminder(reminders[now])

    @schedule_reminders.before_loop
    async def before_schedule_reminders(self):
        """Ensure the bot is ready before starting the reminder loop."""
        await self.bot.wait_until_ready()
        logger.info("Daily reminder schedule started")

def setup(bot: commands.Bot):
    bot.add_cog(DailyReminderCog(bot))
