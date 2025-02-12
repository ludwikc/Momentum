import discord
from discord.ext import commands

class QueueCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Each entry is a tuple (member, join_number)
        self.queue = []
        self.counter = 0  # Unique join number counter
        # Use the dedicated text channel ID for queue updates
        self.target_channel_id = 1120658406160732160
        # Optional TTS flag for speaker announcements (default off)
        self.tts_enabled = False

    def get_target_channel(self):
        channel = self.bot.get_channel(self.target_channel_id)
        return channel

    def format_queue(self):
        """Returns a string with the complete queue listing."""
        if not self.queue:
            return "Nikt nie ma nic do dodania?."
        lines = ["Kolejka:"]
        for member, join_number in self.queue:
            lines.append(f"{join_number}. {member.display_name}")
        return "\n".join(lines)

    @commands.command(name="kolejka")
    async def kolejka(self, ctx):
        """
        Join the speaking queue.
        If the user is already in the queue, a message is sent indicating that.
        Otherwise, the user is added and the updated queue is posted.
        """
        target_channel = self.get_target_channel() or ctx.channel

        # Prevent duplicate queue entries.
        if any(entry[0].id == ctx.author.id for entry in self.queue):
            await target_channel.send(f"{ctx.author.mention}, już jesteś w kolejce, spokojnie! ;) ")
            return

        self.counter += 1
        self.queue.append((ctx.author, self.counter))
        await target_channel.send(self.format_queue())

    @commands.command(name="settts")
    async def settts(self, ctx, mode: str):
        """
        Toggle text-to-speech announcements for speaker updates.
        Usage: !settts on / !settts off
        """
        mode = mode.lower()
        if mode not in ("on", "off"):
            await ctx.send("Usage: !settts on OR !settts off")
            return

        self.tts_enabled = (mode == "on")
        status = "włączone" if self.tts_enabled else "wyłączone"
        await ctx.send(f"Powiadomienia głosowe: {status}.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """
        Listen for voice state updates. If a user unmutes (i.e. goes from self-muted to unmuted)
        and is in the queue, remove them and announce that they are speaking,
        along with the next speakers in the queue.
        """
        # Only process if the user changed from self-muted to unmuted.
        if before.self_mute and not after.self_mute:
            # Find and remove the member from the queue.
            for entry in self.queue:
                if entry[0].id == member.id:
                    self.queue.remove(entry)
                    target_channel = self.get_target_channel() or member.guild.system_channel
                    if not target_channel:
                        return  # No channel available to send updates.

                    # Build the announcement message.
                    lines = [f"{member.display_name} mówi."]
                    if self.queue:
                        lines.append("\nNastępny Lifehacker:")
                        for m, join_number in self.queue:
                            lines.append(f"{join_number}. {m.display_name}")
                    else:
                        lines.append("\nNo i kolejka opustoszała.")

                    announcement = "\n".join(lines)
                    # Use TTS if enabled.
                    await target_channel.send(announcement, tts=self.tts_enabled)
                    break

def setup(bot):
    bot.add_cog(QueueCog(bot))
