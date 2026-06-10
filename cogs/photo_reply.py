import discord
from discord.ext import commands
import logging
from db import upsert_activity, get_user_activity_stats
from config import ACTIVITIES as act

PHOTO_THREAD_ID = 1245416699453509682

logger = logging.getLogger("momentum_bot.photo_reply")


class TreningButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="💪 Dodaj trening",
        style=discord.ButtonStyle.primary,
        custom_id="trening_done_button",
    )
    async def trening_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)

        try:
            result = upsert_activity(user_id, "trening")

            if not result:
                await interaction.response.send_message(
                    "Przepraszam, baza danych jest niedostępna. Spróbuj później.",
                    ephemeral=True,
                )
                return

            streak_count = result.get("streak_count", 1)

            embed = discord.Embed(title="Aktywność", color=0x280586)
            embed.add_field(
                name="",
                value=f"🔥 To {streak_count} trening w tym miesiącu!",
            )

            avatar = interaction.user.avatar or interaction.user.default_avatar
            embed.set_thumbnail(url=avatar.url)

            all_stats = get_user_activity_stats(user_id)
            if all_stats:
                for name, emoji in act.items():
                    streak_key = f"streak_{name}"
                    count = all_stats.get(streak_key, 0)
                    if count > 0:
                        embed.add_field(
                            name=f"{emoji} {name.capitalize()}: {count}",
                            value="",
                            inline=False,
                        )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in trening_button: {e}")
            await interaction.response.send_message(
                "Wystąpił błąd podczas zapisywania aktywności. Spróbuj ponownie później.",
                ephemeral=True,
            )


class PhotoReplyListener(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(TreningButton())
        logger.info("PhotoReplyListener cog initialized")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if message.channel.id != PHOTO_THREAD_ID:
            return

        has_photo = any(
            attachment.content_type and attachment.content_type.startswith("image/")
            for attachment in message.attachments
        )

        if not has_photo:
            return

        try:
            await message.reply(
                "Wszedł trening? Dodaj go na #progress-tracker!",
                view=TreningButton(),
            )
        except Exception as e:
            logger.error(f"Error sending photo reply: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(PhotoReplyListener(bot))
