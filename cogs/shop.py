"""Sklep z kolorami — /sklep, /sklep-admin (StudyLion colour-role shop port).

Items live in Supabase (shop_items) so adding colours needs no deploy. The
Discord role itself is the inventory: colour is single-slot — buying a new one
swaps out other shop roles without refund (upstream semantics, stated in the
UI). The debit is atomic server-side (shop_buy → adjust_coins with a floor).
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging

from config import COINS_EMOJI
from db import adjust_coins, shop_add_item, shop_buy, shop_list, shop_remove_item

logger = logging.getLogger("momentum_bot.shop")

DB_ERROR_MSG = "Wystąpił błąd bazy danych. Spróbuj ponownie później."


def _shop_embed(items: list[dict]) -> discord.Embed:
    embed = discord.Embed(title="🎨 Sklep z kolorami", color=0x280586)
    if not items:
        embed.description = "Sklep jest na razie pusty. Zajrzyj później!"
        return embed
    embed.description = "\n".join(
        f"<@&{item['role_id']}> — **{item['price']}** {COINS_EMOJI}" for item in items
    )
    embed.set_footer(
        text="Kupno nowego koloru zastępuje obecny BEZ zwrotu monet. "
        "Monety zdobywasz m.in. za czas na głosowych i /todo."
    )
    return embed


class ShopView(discord.ui.View):
    def __init__(self, cog: "Shop", owner_id: int, items: list[dict]):
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id
        self.items = {item["role_id"]: item for item in items}
        options = [
            discord.SelectOption(
                label=item["name"][:100],
                value=item["role_id"],
                description=f"{item['price']} monet",
                emoji="🎨",
            )
            for item in items[:25]
        ]
        if options:
            select = discord.ui.Select(placeholder="Wybierz kolor do kupienia…", options=options)
            select.callback = self._on_select
            self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Otwórz własny sklep przez /sklep. 😉", ephemeral=True
            )
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        role_id = interaction.data["values"][0]
        await self.cog.purchase(interaction, role_id, self.items.get(role_id))


class Shop(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("Shop cog initialized")

    sklep_admin = app_commands.Group(
        name="sklep-admin",
        description="(Moderacja) Zarządzanie sklepem z kolorami",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    async def purchase(
        self, interaction: discord.Interaction, role_id: str, item: dict | None
    ):
        member = interaction.user
        guild = interaction.guild
        role = guild.get_role(int(role_id)) if guild else None
        if role is None or item is None:
            await interaction.response.send_message(
                "Tej roli już nie ma w sklepie.", ephemeral=True
            )
            return
        if role in member.roles:
            await interaction.response.send_message(
                f"Masz już kolor {role.mention}. 😎", ephemeral=True
            )
            return
        try:
            result = shop_buy(str(member.id), role_id)
            if not result or not result.get("ok"):
                if result and result.get("error") == "insufficient":
                    await interaction.response.send_message(
                        f"Za mało monet: masz {result.get('balance', 0)} "
                        f"{COINS_EMOJI}, a kolor kosztuje {result.get('price')} "
                        f"{COINS_EMOJI}.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)
                return

            try:
                shop_role_ids = {int(i["role_id"]) for i in shop_list()}
                to_remove = [
                    r for r in member.roles if r.id in shop_role_ids and r.id != role.id
                ]
                if to_remove:
                    await member.remove_roles(
                        *to_remove, reason="Momentum: zmiana koloru ze sklepu"
                    )
                await member.add_roles(role, reason="Momentum: zakup koloru w sklepie")
            except Exception as e:
                # Debit happened but the role failed — refund and apologize.
                logger.error(f"Shop role grant failed for {member.id}: {e}")
                adjust_coins(
                    str(member.id), item["price"], "shop",
                    {"refund": True, "role_id": role_id},
                )
                await interaction.response.send_message(
                    "Nie udało się nadać roli (uprawnienia?). Monety zwrócone.",
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(
                f"🎨 Kupiono kolor {role.mention} za **{item['price']}** "
                f"{COINS_EMOJI}! Zostało Ci {result.get('balance', 0)} {COINS_EMOJI}.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error in shop purchase: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="sklep", description="Kup kolor nicku za monety")
    @app_commands.guild_only()
    async def sklep(self, interaction: discord.Interaction):
        try:
            items = shop_list()
            view = ShopView(self, interaction.user.id, items)
            await interaction.response.send_message(
                embed=_shop_embed(items),
                view=view if items else discord.utils.MISSING,
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error in /sklep: {e}")
            await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @sklep_admin.command(name="dodaj", description="Dodaj (lub zaktualizuj) rolę w sklepie")
    @app_commands.describe(rola="Rola-kolor do sprzedaży", cena="Cena w monetach")
    async def admin_dodaj(
        self,
        interaction: discord.Interaction,
        rola: discord.Role,
        cena: app_commands.Range[int, 0, 1_000_000_000],
    ):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Brak uprawnień.", ephemeral=True)
            return
        me = interaction.guild.me
        if rola.is_default() or rola.managed:
            await interaction.response.send_message(
                "Ta rola nie nadaje się do sklepu.", ephemeral=True
            )
            return
        if rola.permissions.administrator:
            await interaction.response.send_message(
                "Rola z uprawnieniami administratora? Ładna próba. 😄", ephemeral=True
            )
            return
        if me and rola >= me.top_role:
            await interaction.response.send_message(
                "Ta rola jest powyżej mojej najwyższej roli — nie będę mógł jej nadawać.",
                ephemeral=True,
            )
            return
        try:
            shop_add_item(str(rola.id), rola.name, cena)
            await interaction.response.send_message(
                f"✅ {rola.mention} w sklepie za **{cena}** {COINS_EMOJI}.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error in /sklep-admin dodaj: {e}")
            await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @sklep_admin.command(name="usun", description="Usuń rolę ze sklepu")
    @app_commands.describe(rola="Rola do usunięcia ze sklepu")
    async def admin_usun(self, interaction: discord.Interaction, rola: discord.Role):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Brak uprawnień.", ephemeral=True)
            return
        try:
            result = shop_remove_item(str(rola.id))
            if result and result.get("ok"):
                await interaction.response.send_message(
                    f"🗑️ {rola.mention} usunięta ze sklepu.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "Tej roli nie było w sklepie.", ephemeral=True
                )
        except Exception as e:
            logger.error(f"Error in /sklep-admin usun: {e}")
            await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @sklep_admin.command(name="lista", description="Pokaż zawartość sklepu")
    async def admin_lista(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_message(
                embed=_shop_embed(shop_list()), ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in /sklep-admin lista: {e}")
            await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))
