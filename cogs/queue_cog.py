import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import logging
import os
import random
from collections import deque
from datetime import datetime

import db
from config import (
    MOMENTUM_GREETING_LLM_ENABLED,
    MOMENTUM_GREETING_MAX_UNANSWERED,
    MOMENTUM_GREETING_MODEL,
    MOMENTUM_GREETING_TIMEOUT_S,
    MOMENTUM_MODEL,
    MOMENTUM_REASONING_EFFORT,
)
from greetings import (
    DEEPWORK_HELLOS_FALLBACK,
    GREETING_SYSTEM_PROMPT,
    WEEKDAYS_PL,
    build_greeting_prompt,
    decide_greeting_action,
    strip_leading_greeting,
    today_key_warsaw,
)

logger = logging.getLogger("momentum_bot.queue")

VOICE_CHANNEL_ID = 1120658406160732160
DEEPWORK_CHANNEL_ID = 1023996094524424313

try:
    from zoneinfo import ZoneInfo

    _WARSAW = ZoneInfo("Europe/Warsaw")
except Exception:  # pragma: no cover - fallback if tzdata is unavailable
    _WARSAW = None


def _warsaw_now() -> datetime:
    return datetime.now(_WARSAW) if _WARSAW else datetime.now()


def _call_greeting_llm(prompt: str) -> str:
    """One short Chat Completions call for a personalised greeting (blocking).

    Uses the conservative param set straight away: gpt-5.2 rejects
    ``max_tokens``/non-default ``temperature``. The token budget also covers the
    model's hidden reasoning tokens (see the note at config.MOMENTUM_MAX_TOKENS),
    so it keeps headroom above the ~2-sentence reply rather than the bare minimum.
    """
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = MOMENTUM_GREETING_MODEL or MOMENTUM_MODEL
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": GREETING_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_completion_tokens": 300,
    }
    if MOMENTUM_REASONING_EFFORT:
        kwargs["reasoning_effort"] = MOMENTUM_REASONING_EFFORT
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


class GreetingOptOutView(discord.ui.View):
    """Opt-out question shown after MOMENTUM_GREETING_MAX_UNANSWERED unanswered
    greetings. Only the addressee may click; ignoring it leaves the streak ≥ limit
    so the question simply returns the next day."""

    def __init__(self, cog: "QueueCog", asker_id: int):
        super().__init__(timeout=3600)
        self.cog = cog
        self.asker_id = asker_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.asker_id:
            return True
        await interaction.response.send_message(
            "Ta wiadomość jest do kogoś innego 🙂", ephemeral=True
        )
        return False

    @discord.ui.button(label="Pytaj dalej 💪", style=discord.ButtonStyle.primary)
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        try:
            await asyncio.to_thread(
                db.greeting_pref_set_mode, str(self.asker_id), "full", 0
            )
        except Exception as e:
            logger.warning("greeting_pref_set_mode(full) nie powiodło się: %s", e)
        await interaction.response.edit_message(content="Jasne, pytam dalej 💪", view=None)

    @discord.ui.button(label="Nie pytaj — samo cześć", style=discord.ButtonStyle.secondary)
    async def optout(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        try:
            await asyncio.to_thread(
                db.greeting_pref_set_mode, str(self.asker_id), "plain", 0
            )
        except Exception as e:
            logger.warning("greeting_pref_set_mode(plain) nie powiodło się: %s", e)
        await interaction.response.edit_message(
            content="Przyjąłem — od teraz tylko szybkie cześć 👋", view=None
        )

    async def on_timeout(self):
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.NotFound:
            pass


class QueueCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = []  # Lista użytkowników (FIFO), duplikaty dozwolone
        self.current_index = 0  # Indeks aktualnego mówcy
        self.deepwork_greeted = {}  # {user_id: today_key_warsaw()} — raz dziennie
        # Ostatnie wysłane powitania (anty-powtórki w promptcie LLM).
        self.recent_greetings = deque(maxlen=20)
        # {user_id: today_key} — powitanie czekające na odpowiedź użytkownika.
        self.greeted_pending: dict[int, str] = {}
        logger.info("QueueCog initialized")

    def get_voice_channel(self):
        """Get the monitored voice channel"""
        return self.bot.get_channel(VOICE_CHANNEL_ID)

    def _greeting_target_channel(self):
        """Where Deep Work greetings go (and where we watch for replies):
        the guild system channel, falling back to the Deep Work channel itself."""
        ch = self.bot.get_channel(DEEPWORK_CHANNEL_ID)
        if not ch:
            return None
        return ch.guild.system_channel or ch

    async def _generate_greeting(self, member) -> str | None:
        """LLM greeting with a hard timeout; None on disabled/no-key/error/empty."""
        if not MOMENTUM_GREETING_LLM_ENABLED or not os.getenv("OPENAI_API_KEY"):
            return None
        now = _warsaw_now()
        prompt = build_greeting_prompt(
            member.display_name,
            WEEKDAYS_PL.get(now.weekday(), ""),
            now.strftime("%H:%M"),
            list(self.recent_greetings),
        )
        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(_call_greeting_llm, prompt),
                timeout=MOMENTUM_GREETING_TIMEOUT_S,
            )
        except Exception as e:
            logger.warning("Powitanie LLM nie powiodło się (%s) — fallback statyczny", e)
            return None
        # We already prepend "Cześć @imię!" — drop any greeting the model added anyway.
        return strip_leading_greeting(text) or None

    async def _greet_deepwork(self, member, channel, today: str):
        """Send the right greeting for a Deep Work join, per the user's stored pref."""
        allow = discord.AllowedMentions(everyone=False, roles=False, users=True)
        try:
            mode, streak = await asyncio.to_thread(db.greeting_pref_get, str(member.id))
        except Exception as e:
            # Fail-open: a Supabase hiccup never leaves the channel un-greeted.
            logger.warning("greeting_pref_get nie powiodło się (%s) — full/0", e)
            mode, streak = "full", 0

        action = decide_greeting_action(mode, streak, MOMENTUM_GREETING_MAX_UNANSWERED)

        if action == "plain":
            await channel.send(f"Cześć {member.mention} 👋", allowed_mentions=allow)
            return

        if action == "ask":
            view = GreetingOptOutView(self, member.id)
            view.message = await channel.send(
                f"Hej {member.mention} — widzę, że nie odpowiadasz na moje pytania. "
                "Przestać Cię witać na tym kanale?",
                view=view,
                allowed_mentions=allow,
            )
            logger.info("Pytanie opt-out powitań dla %s", member.id)
            return

        # action == "full": LLM greeting with static fallback.
        text = await self._generate_greeting(member) or random.choice(
            DEEPWORK_HELLOS_FALLBACK
        )
        await channel.send(f"Cześć {member.mention}! {text}", allowed_mentions=allow)
        self.recent_greetings.append(text)
        self.greeted_pending[member.id] = today
        try:
            await asyncio.to_thread(db.greeting_streak_set, str(member.id), streak + 1)
        except Exception as e:
            logger.warning("greeting_streak_set nie powiodło się: %s", e)

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
    async def on_message(self, message: discord.Message):
        """Detect a reply to a pending greeting → reset the unanswered streak.

        Light heuristic: any message from the user, same Warsaw day, on the
        channel the greeting went to — no content analysis (plan §Detekcja)."""
        if message.author.bot:
            return
        target = self._greeting_target_channel()
        if not target or message.channel.id != target.id:
            return
        if self.greeted_pending.get(message.author.id) != today_key_warsaw():
            return
        self.greeted_pending.pop(message.author.id, None)
        try:
            await asyncio.to_thread(db.greeting_streak_set, str(message.author.id), 0)
        except Exception as e:
            logger.warning("greeting_streak_set(0) nie powiodło się: %s", e)

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

        # Greet user joining the deepwork voice channel (once per Warsaw day)
        joined_deepwork = (before.channel is None or before.channel.id != DEEPWORK_CHANNEL_ID) and \
                          after.channel is not None and after.channel.id == DEEPWORK_CHANNEL_ID
        if joined_deepwork and not member.bot:
            today = today_key_warsaw()
            if self.deepwork_greeted.get(member.id) != today:
                self.deepwork_greeted[member.id] = today
                target = self._greeting_target_channel()
                if target:
                    await self._greet_deepwork(member, target, today)

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
