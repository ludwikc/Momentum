"""Weekly Daily-Coaching digest: every Friday 14:00 (Warsaw) DM the owner a
ready-to-paste #ogłoszenia announcement summarizing the week's 12:34 meetings.

Data: local transcripts store (transcripts.py). Voice: digest.DIGEST_SYSTEM_PROMPT
(condensed rewriter-discord patterns). One OpenAI call per digest, off-thread,
same lazy-client pattern as transcribe.py/przywolanie.py. The slash command
/podsumowanie-tygodnia (owner-only) triggers the same DM on demand — the test
path that doesn't wait for Friday.
"""
import asyncio
import datetime
import logging
import os

import discord
import pytz
from discord import app_commands
from discord.ext import commands, tasks

import digest
import transcripts
from config import (
    MOMENTUM_MODEL,
    MOMENTUM_OWNER_ID,
    RECORDING_NOTIFY_CHANNEL_ID,
    WEEKLY_DIGEST_CHANNEL_KEY,
    WEEKLY_DIGEST_ENABLED,
    WEEKLY_DIGEST_LOOKBACK_DAYS,
    WEEKLY_DIGEST_MAX_TOKENS,
    WEEKLY_DIGEST_PER_MEETING_CHARS,
    WEEKLY_DIGEST_TIME,
    WEEKLY_DIGEST_WEEKDAY,
)
from summon import split_for_discord

logger = logging.getLogger("momentum_bot.weekly_digest")


def _generate_post(system_prompt: str, user_prompt: str) -> str:
    """One chat completion for the digest. Blocking — call via asyncio.to_thread.

    MOMENTUM_MODEL (gpt-5.2) rejects max_tokens/non-default temperature, so we
    send max_completion_tokens from the start and never touch temperature.
    """
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=120)
    resp = client.chat.completions.create(
        model=MOMENTUM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=WEEKLY_DIGEST_MAX_TOKENS,
    )
    return (resp.choices[0].message.content or "").strip()


class WeeklyDigest(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.warsaw = pytz.timezone("Europe/Warsaw")
        self._last_sent_date = None  # once-per-day guard, daily_invite pattern
        logger.info("WeeklyDigest cog initialized")

    @commands.Cog.listener()
    async def on_ready(self):
        if WEEKLY_DIGEST_ENABLED and not self.schedule_digest.is_running():
            self.schedule_digest.start()
            logger.info(
                "Weekly digest scheduled: weekday=%s %s (Warsaw)",
                WEEKLY_DIGEST_WEEKDAY, WEEKLY_DIGEST_TIME,
            )

    def cog_unload(self):
        if self.schedule_digest.is_running():
            self.schedule_digest.cancel()

    @tasks.loop(minutes=1)
    async def schedule_digest(self):
        now = datetime.datetime.now(self.warsaw)
        if (now.weekday() != WEEKLY_DIGEST_WEEKDAY
                or now.strftime("%H:%M") != WEEKLY_DIGEST_TIME
                or self._last_sent_date == now.date()):
            return
        self._last_sent_date = now.date()
        try:
            await self._send_digest()
        except Exception:
            logger.exception("Weekly digest failed")
            channel = self.bot.get_channel(RECORDING_NOTIFY_CHANNEL_ID)
            if channel:
                try:
                    await channel.send(
                        "⚠️ Piątkowy digest Daily Coaching nie wyszedł (szczegóły w logach) "
                        "— odpal /podsumowanie-tygodnia, jak ogarniesz przyczynę."
                    )
                except Exception:
                    pass

    @schedule_digest.before_loop
    async def before_schedule_digest(self):
        await self.bot.wait_until_ready()

    async def _send_digest(self) -> str:
        """Collect the week's meetings, generate the announcement, DM the owner.

        Returns a short status string (also used by the slash command reply).
        Every degraded path still sends a DM — a silent Friday looks broken.
        """
        owner = await self.bot.fetch_user(MOMENTUM_OWNER_ID)
        now = datetime.datetime.now(self.warsaw)
        week_label = f"{(now - datetime.timedelta(days=6)):%d.%m}–{now:%d.%m}"

        items = await asyncio.to_thread(
            lambda: transcripts.list_transcripts(
                WEEKLY_DIGEST_LOOKBACK_DAYS, today=now.date()
            )
        )
        meetings = digest.select_daily_meetings(
            items, channel_key=WEEKLY_DIGEST_CHANNEL_KEY
        )
        meetings.reverse()  # list_transcripts is newest-first; digest reads chronologically

        if not meetings:
            await owner.send(
                f"📋 Piątkowe podsumowanie ({week_label}): w tym tygodniu nie mam "
                "żadnych transkryptów z Daily Coaching — nie ma z czego złożyć ogłoszenia."
            )
            return "brak spotkań"

        if not os.getenv("OPENAI_API_KEY"):
            days = ", ".join(m["data"][:10] for m in meetings)
            await owner.send(
                f"📋 Piątkowe podsumowanie ({week_label}): mam {len(meetings)} "
                f"transkryptów ({days}), ale brak OPENAI_API_KEY — nie wygeneruję wzoru."
            )
            return "brak klucza OpenAI"

        enriched = []
        for m in meetings:
            body = await asyncio.to_thread(transcripts.read_transcript, m["id"])
            if not body:
                continue
            enriched.append({
                "data": m["data"],
                "uczestnicy": m.get("uczestnicy") or [],
                "body": body[:WEEKLY_DIGEST_PER_MEETING_CHARS],
            })
        if not enriched:
            await owner.send(
                f"📋 Piątkowe podsumowanie ({week_label}): transkrypty z tego "
                "tygodnia są puste/nieczytelne — nie wygeneruję wzoru."
            )
            return "puste transkrypty"

        system_prompt, user_prompt = digest.build_digest_messages(
            enriched, week_label=week_label
        )
        post = await asyncio.to_thread(_generate_post, system_prompt, user_prompt)
        if not post:
            await owner.send(
                f"📋 Piątkowe podsumowanie ({week_label}): model zwrócił pustą "
                "odpowiedź — spróbuj ponownie przez /podsumowanie-tygodnia."
            )
            return "pusta odpowiedź modelu"

        for chunk in split_for_discord(digest.build_dm_text(post)):
            await owner.send(chunk)
        logger.info("Weekly digest DM sent (%d meetings, %s)", len(enriched), week_label)
        return f"wysłane ({len(enriched)} spotkań)"

    @app_commands.command(
        name="podsumowanie-tygodnia",
        description="(owner) Wyślij mi DM z wzorem cotygodniowego ogłoszenia Daily Coaching.",
    )
    async def podsumowanie_tygodnia(self, interaction: discord.Interaction):
        if interaction.user.id != MOMENTUM_OWNER_ID:
            await interaction.response.send_message(
                "Ta komenda jest tylko dla właściciela bota.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            status = await self._send_digest()
            self._last_sent_date = datetime.datetime.now(self.warsaw).date()
            note = ""
            if datetime.datetime.now(self.warsaw).weekday() == WEEKLY_DIGEST_WEEKDAY:
                note = " Dzisiejszy automat o " + WEEKLY_DIGEST_TIME + " już nie wyjdzie (guard ustawiony)."
            await interaction.followup.send(f"Gotowe — {status}. Sprawdź DM 📬{note}")
        except Exception as e:
            logger.exception("Digest via slash failed")
            await interaction.followup.send(f"Nie wyszło: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(WeeklyDigest(bot))
