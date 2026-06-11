import discord
from discord.ext import commands
import logging
from db import upsert_activity, get_user_activity_stats
from config import PROGRESS_CHANNEL_ID
from activity_embed import build_activity_embed

PHOTO_THREAD_ID = 1245416699453509682

logger = logging.getLogger("momentum_bot.photo_reply")


class TreningButton(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=86400)  # 24 h; use /done after that
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Ten przycisk jest tylko dla autora zdjęcia. Użyj /done, żeby dodać swój trening.",
                ephemeral=True,
            )
            return False
        return True

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

            all_stats = get_user_activity_stats(user_id)
            embed = build_activity_embed(
                interaction.user, "trening", result, all_stats
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)

            progress_channel = interaction.client.get_channel(PROGRESS_CHANNEL_ID)
            if progress_channel:
                await progress_channel.send(
                    content=interaction.user.mention,
                    embed=embed,
                )

        except Exception as e:
            logger.error(f"Error in trening_button: {e}")
            await interaction.response.send_message(
                "Wystąpił błąd podczas zapisywania aktywności. Spróbuj ponownie później.",
                ephemeral=True,
            )


class PhotoReplyListener(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
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
                view=TreningButton(author_id=message.author.id),
            )
        except Exception as e:
            logger.error(f"Error sending photo reply: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(PhotoReplyListener(bot))
