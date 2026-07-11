"""Monety — the coin economy (StudyLion port).

/portfel — balance + earnings, /przelew — member→member transfer,
/monety-admin — owner-only grant/deduction. Earning happens elsewhere:
voice tracker, todo rewards, /done and GM hooks.
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging

from config import COINS_EMOJI
from db import adjust_coins, get_coin_summary, transfer_coins

OWNER_ID = 404038151565213696

logger = logging.getLogger("momentum_bot.economy")


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("Economy cog initialized")

    @app_commands.command(
        name="portfel", description="Pokaż stan monet (swój lub innej osoby)"
    )
    @app_commands.describe(uzytkownik="Czyj portfel pokazać (domyślnie Twój)")
    async def portfel(
        self,
        interaction: discord.Interaction,
        uzytkownik: discord.Member | None = None,
    ):
        member = uzytkownik or interaction.user
        if member.bot:
            await interaction.response.send_message(
                "Boty pracują za darmo. 🤖", ephemeral=True
            )
            return
        try:
            summary = get_coin_summary(str(member.id)) or {}
            embed = discord.Embed(title=f"{COINS_EMOJI} Portfel", color=0x280586)
            avatar = member.avatar or member.default_avatar
            embed.set_thumbnail(url=avatar.url)
            embed.add_field(
                name=f"Stan konta: {summary.get('balance', 0)} {COINS_EMOJI}",
                value="",
                inline=False,
            )
            embed.add_field(
                name=f"Zarobione w tym miesiącu: {summary.get('earned_month', 0)}",
                value="",
                inline=False,
            )
            embed.add_field(
                name=f"Zarobione łącznie: {summary.get('earned_total', 0)}",
                value="",
                inline=False,
            )
            embed.set_footer(
                text="Monety zdobywasz za czas na głosowych, zadania z /todo, /done i GM."
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"Error in /portfel: {e}")
            await interaction.response.send_message(
                "Wystąpił błąd podczas pobierania portfela. Spróbuj ponownie później.",
                ephemeral=True,
            )

    @app_commands.command(
        name="przelew", description="Przekaż monety innej osobie"
    )
    @app_commands.describe(komu="Komu przelać", ile="Ile monet (min. 1)")
    async def przelew(
        self,
        interaction: discord.Interaction,
        komu: discord.Member,
        ile: app_commands.Range[int, 1, 1_000_000_000],
    ):
        if komu.id == interaction.user.id:
            await interaction.response.send_message(
                "Przelew do samego siebie? To się nazywa optymalizacja podatkowa. 😏",
                ephemeral=True,
            )
            return
        if komu.bot:
            await interaction.response.send_message(
                "Boty nie przyjmują napiwków. 🤖", ephemeral=True
            )
            return
        try:
            result = transfer_coins(str(interaction.user.id), str(komu.id), ile)
            if not result or not result.get("ok"):
                if result and result.get("error") == "insufficient":
                    await interaction.response.send_message(
                        f"Za mało monet — masz {result.get('balance', 0)} {COINS_EMOJI}.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "Nie udało się wykonać przelewu. Spróbuj ponownie później.",
                        ephemeral=True,
                    )
                return

            await interaction.response.send_message(
                f"{COINS_EMOJI} {interaction.user.mention} przekazuje "
                f"**{ile}** monet {komu.mention}!"
            )
            # Best-effort DM notice (mirrors StudyLion /send).
            try:
                await komu.send(
                    f"{COINS_EMOJI} {interaction.user.display_name} przekazał(a) Ci "
                    f"**{ile}** monet na serwerze Lifehackerzy!"
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error in /przelew: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Wystąpił błąd podczas przelewu. Spróbuj ponownie później.",
                    ephemeral=True,
                )

    @app_commands.command(
        name="monety-admin",
        description="(Admin) Dodaj lub odejmij monety użytkownikowi",
    )
    @app_commands.describe(
        komu="Komu zmienić stan konta",
        ile="Ile monet dodać (ujemne = odjąć)",
    )
    async def monety_admin(
        self,
        interaction: discord.Interaction,
        komu: discord.Member,
        ile: app_commands.Range[int, -1_000_000_000, 1_000_000_000],
    ):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "Ta komenda jest tylko dla właściciela bota.", ephemeral=True
            )
            return
        try:
            result = adjust_coins(
                str(komu.id), ile, "admin", {"by": str(interaction.user.id)}
            )
            if not result or not result.get("ok"):
                await interaction.response.send_message(
                    f"Nie udało się (saldo: {result.get('balance', '?') if result else '?'}).",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                f"OK — nowe saldo {komu.display_name}: "
                f"{result.get('balance', 0)} {COINS_EMOJI}.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error in /monety-admin: {e}")
            await interaction.response.send_message(
                "Wystąpił błąd. Spróbuj ponownie później.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
