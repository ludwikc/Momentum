import discord
from discord.ext import commands
import asyncio

class QueueCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = []  # Lista uczestników jako krotki: (member, join_number)
        self.counter = 0  # Unikalny licznik dla pozycji w kolejce
        self.target_channel_id = 1120658406160732160  # Kanał do komunikatów
        self.current_speaker_id = None  # Aktualnie mówiący
        self.speaking_times = {}  # Śledzenie czasu rozpoczęcia mówienia

    def get_target_channel(self):
        return self.bot.get_channel(self.target_channel_id)

    def format_queue(self):
        """Formatowanie kolejki, pogrubia aktualnie mówiącego"""
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

    @commands.command(name="kolejka")
    async def kolejka(self, ctx):
        """Dodanie użytkownika do kolejki"""
        target_channel = self.get_target_channel() or ctx.channel
        if any(entry[0].id == ctx.author.id for entry in self.queue):
            await target_channel.send(f"{ctx.author.mention}, już jesteś w kolejce! 😉")
            return
        self.counter += 1
        self.queue.append((ctx.author, self.counter))
        await target_channel.send(self.format_queue())

    @commands.command(name="kolejka_next")
    async def kolejka_next(self, ctx):
        """Przesuwa kolejkę do następnej osoby"""
        target_channel = self.get_target_channel() or ctx.channel
        if not self.queue:
            await target_channel.send("Kolejka jest pusta.")
            return
        self.current_speaker_id = None
        self.queue.pop(0)  # Usunięcie pierwszej osoby z kolejki
        if self.queue:
            await target_channel.send(f"{self.queue[0][0].mention}, Twoja kolej!")
            await target_channel.send(self.format_queue())
        else:
            await target_channel.send("No i kolejka opustoszała.")
            self.counter = 0

    @commands.command(name="kolejka_done")
    async def kolejka_done(self, ctx):
        """Pozwala użytkownikowi zakończyć swoją kolej bez mutowania"""
        target_channel = self.get_target_channel() or ctx.channel
        if self.current_speaker_id != ctx.author.id:
            await target_channel.send(f"{ctx.author.mention}, to nie Twoja kolej! 😉")
            return
        await self.kolejka_next(ctx)  # Przejście do kolejnej osoby

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Monitoruje mute/unmute, ignoruje krótkie przerwy na komentarze"""
        target_channel = self.get_target_channel()
        if not target_channel:
            return

        # Użytkownik odmutował się (muted → unmuted)
        if before.self_mute and not after.self_mute:
            if self.queue and self.queue[0][0].id == member.id:
                self.current_speaker_id = member.id
                self.speaking_times[member.id] = asyncio.get_event_loop().time()  # Rejestrujemy czas rozpoczęcia mówienia
                await target_channel.send(f"{member.display_name} mówi.")
                await target_channel.send(self.format_queue())

        # Użytkownik wyciszył się (unmuted → muted)
        if not before.self_mute and after.self_mute:
            if self.current_speaker_id == member.id:
                # Sprawdzamy, ile mówił użytkownik
                start_time = self.speaking_times.get(member.id, 0)
                speaking_duration = asyncio.get_event_loop().time() - start_time

                # Jeśli użytkownik mówił mniej niż 5 sekund, traktujemy to jako komentarz
                if speaking_duration < 5:
                    return

                await self.kolejka_next(commands.Context(bot=self.bot, message=None))  # Przejście do kolejnej osoby

    @commands.Cog.listener()
    async def on_message(self, message):
        """Zapobiega przypadkowemu wpisaniu "kolejka" bez wykrzyknika"""
        if message.author.bot:
            return
        if message.content.strip().lower() == "kolejka":
            await message.channel.send(f"{message.author.mention}, aby dołączyć do kolejki, użyj `!kolejka`.")
            return
        await self.bot.process_commands(message)

def setup(bot):
    bot.add_cog(QueueCog(bot))