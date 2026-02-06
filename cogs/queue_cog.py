import discord
from discord.ext import commands
from discord import app_commands
import logging
import random
from datetime import date

logger = logging.getLogger("momentum_bot.queue")

VOICE_CHANNEL_ID = 1120658406160732160
DEEPWORK_CHANNEL_ID = 1023996094524424313

DEEPWORK_HELLOS = [
    "Nad czym będziesz dziś pracować?",
    "Co jest dzisiaj Twoim MIT (Most Important Task)?",
    "Jaki efekt chcesz zobaczyć za 90 minut?",
    "Co dziś dowozisz?",
    "Które zadanie z Twojej listy najbardziej Cię dziś uwiera?",
    "Czas zjeść jakąś 'żabę'? ;)",
]


class QueueCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = []  # Lista użytkowników (FIFO), duplikaty dozwolone
        self.current_index = 0  # Indeks aktualnego mówcy
        self.deepwork_greeted = {}  # {user_id: date} — raz dziennie
        logger.info("QueueCog initialized")

    def get_voice_channel(self):
        """Get the monitored voice channel"""
        return self.bot.get_channel(VOICE_CHANNEL_ID)

    def format_queue(self):
        """Format queue with arrow at current speaker"""
        if not self.queue:
            return "Kolejka jest pusta."

        lines = []
        for i, member in enumerate(self.queue):
            if i == self.current_index:
                lines.append(f"{i + 1}. {member.display_name} ←")
            else:
                lines.append(f"{i + 1}. {member.display_name}")
        return "\n".join(lines)

    @app_commands.command(name="kolejka", description="Dodaj siebie do kolejki do mówienia")
    async def kolejka(self, interaction: discord.Interaction):
        """Add user to the queue"""
        self.queue.append(interaction.user)
        await interaction.response.send_message(self.format_queue())

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Monitor voice channel joins, mute/unmute and channel leave events"""
        voice_channel = self.get_voice_channel()
        if not voice_channel:
            return

        # Greet user joining the monitored voice channel
        joined_main = (before.channel is None or before.channel.id != VOICE_CHANNEL_ID) and \
                      after.channel is not None and after.channel.id == VOICE_CHANNEL_ID
        if joined_main and not member.bot:
            text_channel = voice_channel.guild.system_channel or voice_channel
            await text_channel.send(f"Cześć {member.mention}")

        # Greet user joining the deepwork voice channel (once per day)
        joined_deepwork = (before.channel is None or before.channel.id != DEEPWORK_CHANNEL_ID) and \
                          after.channel is not None and after.channel.id == DEEPWORK_CHANNEL_ID
        if joined_deepwork and not member.bot:
            today = date.today()
            if self.deepwork_greeted.get(member.id) != today:
                self.deepwork_greeted[member.id] = today
                deepwork_channel = self.bot.get_channel(DEEPWORK_CHANNEL_ID)
                if deepwork_channel:
                    text_channel = deepwork_channel.guild.system_channel or deepwork_channel
                    await text_channel.send(
                        f"Cześć {member.mention}! {random.choice(DEEPWORK_HELLOS)}"
                    )

        # Czyszczenie kolejki gdy kanał jest pusty
        if len(voice_channel.members) == 0:
            self.queue = []
            self.current_index = 0
            return

        # Ignoruj jeśli kolejka skończona
        if self.current_index >= len(self.queue):
            return

        # Ignoruj jeśli użytkownik nie jest na monitorowanym kanale
        user_channel = after.channel or before.channel
        if not user_channel or user_channel.id != VOICE_CHANNEL_ID:
            return

        current_speaker = self.queue[self.current_index]

        # Unmute (mute → unmute)
        if before.self_mute and not after.self_mute:
            if member.id == current_speaker.id:
                # Aktualny mówca zaczął mówić - wyślij stan kolejki
                text_channel = voice_channel.guild.system_channel or voice_channel
                await text_channel.send(self.format_queue())

        # Mute (unmute → mute)
        elif not before.self_mute and after.self_mute:
            if member.id == current_speaker.id:
                # Aktualny mówca skończył - przejdź do następnego
                self.current_index += 1
                text_channel = voice_channel.guild.system_channel or voice_channel
                await text_channel.send(self.format_queue())


async def setup(bot):
    await bot.add_cog(QueueCog(bot))
