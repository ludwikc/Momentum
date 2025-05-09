import discord
from discord.ext import commands
from discord.commands import slash_command, Option
import asyncio
import logging

logger = logging.getLogger("momentum_bot.queue")

class QueueCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = []  # List of participants as tuples: (member, join_number)
        self.counter = 0  # Unique counter for queue position
        self.target_channel_id = 1120658406160732160  # Channel for announcements
        self.current_speaker_id = None  # Currently speaking
        self.speaking_times = {}  # Track speaking start times

    def get_target_channel(self):
        """Get the target channel or None if it doesn't exist"""
        return self.bot.get_channel(self.target_channel_id)

    def format_queue(self):
        """Format the queue, bolding the current speaker"""
        if not self.queue:
            return "Nikt nie ma nic do dodania."
        lines = ["Kolejka:"]
        for index, (member, join_number) in enumerate(self.queue):
            if self.current_speaker_id and member.id == self.current_speaker_id:
                line = f"{join_number}. **{member.display_name}**"
            else:
                line = f"{join_number}. {member.display_name}"
            lines.append(line)
        return "\n".join(lines)

    @slash_command(name="kolejka", description="Dodaj siebie do kolejki do mówienia")
    async def kolejka_slash(self, ctx):
        """Add user to the queue"""
        target_channel = self.get_target_channel() or ctx.channel
        
        # Check if user is already in queue
        if any(entry[0].id == ctx.author.id for entry in self.queue):
            await ctx.respond(f"{ctx.author.mention}, już jesteś w kolejce! 😉")
            return
            
        # Add user to queue
        self.counter += 1
        self.queue.append((ctx.author, self.counter))
        await ctx.respond(self.format_queue())

    @slash_command(name="kolejka_next", description="Przejdź do następnej osoby w kolejce")
    async def kolejka_next_slash(self, ctx):
        """Move queue to next person"""
        target_channel = self.get_target_channel() or ctx.channel
        
        if not self.queue:
            await ctx.respond("Kolejka jest pusta.")
            return
            
        self.current_speaker_id = None
        self.queue.pop(0)  # Remove first person from queue
        
        if self.queue:
            next_speaker = self.queue[0][0]
            await ctx.respond(f"{next_speaker.mention}, Twoja kolej!")
            await target_channel.send(self.format_queue())
        else:
            await ctx.respond("No i kolejka opustoszała.")
            self.counter = 0

    @slash_command(name="kolejka_done", description="Zakończ swoją kolej mówienia")
    async def kolejka_done_slash(self, ctx):
        """Allow user to finish their turn without muting"""
        target_channel = self.get_target_channel() or ctx.channel
        
        if not self.queue:
            await ctx.respond("Kolejka jest pusta.")
            return
            
        # Check if user is current speaker or first in queue
        is_speaker = self.current_speaker_id == ctx.author.id
        is_first_in_queue = self.queue and self.queue[0][0].id == ctx.author.id
        
        if not (is_speaker or is_first_in_queue):
            await ctx.respond(f"{ctx.author.mention}, to nie Twoja kolej! 😉")
            return
        
        self.current_speaker_id = None
        self.queue.pop(0)  # Remove first person from queue
        
        if self.queue:
            next_speaker = self.queue[0][0]
            await ctx.respond(f"{next_speaker.mention}, Twoja kolej!")
            await target_channel.send(self.format_queue())
        else:
            await ctx.respond("No i kolejka opustoszała.")
            self.counter = 0

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Monitor mute/unmute, ignore short breaks for comments"""
        target_channel = self.get_target_channel()
        if not target_channel:
            return

        # User unmuted (muted → unmuted)
        if before.self_mute and not after.self_mute:
            if self.queue and self.queue[0][0].id == member.id:
                self.current_speaker_id = member.id
                self.speaking_times[member.id] = asyncio.get_event_loop().time()  # Register speaking start time
                await target_channel.send(f"{member.display_name} mówi.")
                await target_channel.send(self.format_queue())

        # User muted (unmuted → muted)
        elif not before.self_mute and after.self_mute:
            if self.current_speaker_id == member.id:
                # Check how long user was speaking
                start_time = self.speaking_times.get(member.id, 0)
                speaking_duration = asyncio.get_event_loop().time() - start_time

                # If user spoke less than 5 seconds, treat as comment
                if speaking_duration < 5:
                    return

                # Create fake context for kolejka_next
                class FakeContext:
                    def __init__(self, author, channel, bot):
                        self.author = author
                        self.channel = channel
                        self.bot = bot
                        
                    async def respond(self, content):
                        await self.channel.send(content)
                
                fake_ctx = FakeContext(member, target_channel, self.bot)
                await self.kolejka_next_slash(fake_ctx)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Redirect traditional "!kolejka" commands to slash command"""
        if message.author.bot:
            return
            
        content = message.content.strip().lower()
        if content == "kolejka" or content == "!kolejka":
            await message.channel.send(f"{message.author.mention}, aby dołączyć do kolejki, użyj `/kolejka` (slash command).")

async def setup(bot):
    await bot.add_cog(QueueCog(bot))
