"""Lista zadań — /todo (StudyLion tasklist port, flat v1).

Numbering is the 1-based position on the live list (completed tasks stay
listed, struck through, until removed — so numbers are stable). Completing a
task mints coins (once per task, max TASK_REWARD_LIMIT_24H per rolling 24h),
handled server-side in the todo_set_done RPC.
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging

from config import (
    COINS_EMOJI,
    TASK_REWARD_COINS,
    TASK_REWARD_LIMIT_24H,
    TODO_MAX_CONTENT,
    TODO_MAX_OPEN,
)
from db import todo_add, todo_edit, todo_list, todo_remove, todo_set_done
from parsers import parse_index_ranges

logger = logging.getLogger("momentum_bot.todo")

MAX_LIST_LINES = 40

DB_ERROR_MSG = "Wystąpił błąd bazy danych. Spróbuj ponownie później."
BAD_RANGE_MSG = (
    "Nie rozumiem tych numerów. Podaj np. `3`, `1,3`, `2-5` albo `all` "
    "(numery znajdziesz w `/todo lista`)."
)


def _render_list(user: discord.User | discord.Member, items: list[dict]) -> discord.Embed:
    """The tasklist embed: N/M header, strikethrough for completed items."""
    done_count = sum(1 for i in items if i.get("completed_at"))
    embed = discord.Embed(
        title=f"📋 Lista zadań — {done_count}/{len(items)} ukończone",
        color=0x280586,
    )
    if not items:
        embed.description = "Pusto! Dodaj pierwsze zadanie: `/todo dodaj`"
        return embed

    lines = []
    for idx, item in enumerate(items[:MAX_LIST_LINES], start=1):
        if item.get("completed_at"):
            lines.append(f"**{idx}.** ~~{item['content']}~~ ✅")
        else:
            lines.append(f"**{idx}.** {item['content']}")
    if len(items) > MAX_LIST_LINES:
        lines.append(f"…i {len(items) - MAX_LIST_LINES} kolejnych")
    embed.description = "\n".join(lines)
    embed.set_footer(
        text=f"{COINS_EMOJI} +{TASK_REWARD_COINS} za ukończone zadanie "
        f"(max {TASK_REWARD_LIMIT_24H}/24h) · odhacz: /todo zrobione lub menu poniżej"
    )
    return embed


class TodoToggleView(discord.ui.View):
    """Author-locked select that flips completion for the chosen tasks —
    the one interactive piece kept from StudyLion's tasklist widget."""

    def __init__(self, cog: "Todo", owner_id: int, items: list[dict]):
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = owner_id
        self.message: discord.Message | None = None
        self._build(items)

    def _build(self, items: list[dict]):
        self.clear_items()
        options = []
        for idx, item in enumerate(items[:25], start=1):
            done = bool(item.get("completed_at"))
            options.append(
                discord.SelectOption(
                    label=f"{idx}. {item['content']}"[:100],
                    value=str(item["id"]),
                    emoji="✅" if done else "⬜",
                    description="odznacz" if done else "odhacz",
                )
            )
        if options:
            select = discord.ui.Select(
                placeholder="Przełącz wybrane zadania…",
                min_values=1,
                max_values=len(options),
                options=options,
            )
            select.callback = self._on_select
            self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "To nie jest Twoja lista zadań!", ephemeral=True
            )
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        try:
            selected = {int(v) for v in interaction.data["values"]}
            items = todo_list(str(self.owner_id))
            by_id = {i["id"]: i for i in items}
            to_tick = [i for i in selected if i in by_id and not by_id[i].get("completed_at")]
            to_untick = [i for i in selected if i in by_id and by_id[i].get("completed_at")]

            minted = 0
            if to_tick:
                result = todo_set_done(
                    str(self.owner_id), to_tick, True,
                    TASK_REWARD_COINS, TASK_REWARD_LIMIT_24H,
                )
                minted = (result or {}).get("coins_minted", 0)
            if to_untick:
                todo_set_done(str(self.owner_id), to_untick, False)

            items = todo_list(str(self.owner_id))
            self._build(items)
            await interaction.response.edit_message(
                embed=_render_list(interaction.user, items), view=self
            )
            if minted:
                await interaction.followup.send(
                    f"{COINS_EMOJI} +{minted} monet za ukończone zadania!",
                    ephemeral=True,
                )
        except Exception as e:
            logger.error(f"Todo toggle error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


@app_commands.guild_only()
class Todo(commands.GroupCog, group_name="todo", description="Twoja lista zadań"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("Todo cog initialized")

    async def _resolve_indices(
        self, interaction: discord.Interaction, numery: str
    ) -> list[int] | None:
        """Map a user range-string to task ids; replies with the error itself."""
        items = todo_list(str(interaction.user.id))
        if not items:
            await interaction.response.send_message(
                "Twoja lista jest pusta — dodaj coś przez `/todo dodaj`.",
                ephemeral=True,
            )
            return None
        indices = parse_index_ranges(numery, len(items))
        if indices is None:
            await interaction.response.send_message(BAD_RANGE_MSG, ephemeral=True)
            return None
        return [items[i - 1]["id"] for i in indices]

    @app_commands.command(name="dodaj", description="Dodaj zadanie (kilka: rozdziel średnikiem)")
    @app_commands.describe(tresc="Treść zadania; kilka zadań rozdziel `;`")
    async def dodaj(self, interaction: discord.Interaction, tresc: str):
        pieces = [p.strip() for p in tresc.split(";") if p.strip()]
        if not pieces:
            await interaction.response.send_message(
                "Podaj treść zadania.", ephemeral=True
            )
            return
        too_long = [p for p in pieces if len(p) > TODO_MAX_CONTENT]
        if too_long:
            await interaction.response.send_message(
                f"Zadanie może mieć najwyżej {TODO_MAX_CONTENT} znaków "
                f"(za długie: „{too_long[0][:50]}…”).",
                ephemeral=True,
            )
            return
        try:
            result = todo_add(str(interaction.user.id), pieces, TODO_MAX_OPEN)
            if not result or not result.get("ok"):
                if result and result.get("error") == "limit":
                    await interaction.response.send_message(
                        f"Masz już {result.get('open_count')} otwartych zadań "
                        f"(limit {TODO_MAX_OPEN}). Odhacz coś najpierw. 😉",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)
                return
            added = result.get("added", len(pieces))
            word = "zadanie" if added == 1 else ("zadania" if added < 5 else "zadań")
            await interaction.response.send_message(
                f"➕ Dodano {added} {word}. Zobacz: `/todo lista`.", ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in /todo dodaj: {e}")
            await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="lista", description="Pokaż swoją listę zadań")
    async def lista(self, interaction: discord.Interaction):
        try:
            items = todo_list(str(interaction.user.id))
            view = TodoToggleView(self, interaction.user.id, items)
            await interaction.response.send_message(
                embed=_render_list(interaction.user, items),
                view=view,
                ephemeral=True,
            )
            view.message = await interaction.original_response()
        except Exception as e:
            logger.error(f"Error in /todo lista: {e}")
            await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="zrobione", description="Odhacz zadania (np. 1,3-5 albo all)")
    @app_commands.describe(numery="Numery z /todo lista, np. `2` albo `1,3-5` albo `all`")
    async def zrobione(self, interaction: discord.Interaction, numery: str):
        try:
            ids = await self._resolve_indices(interaction, numery)
            if ids is None:
                return
            result = todo_set_done(
                str(interaction.user.id), ids, True,
                TASK_REWARD_COINS, TASK_REWARD_LIMIT_24H,
            )
            changed = (result or {}).get("changed", 0)
            minted = (result or {}).get("coins_minted", 0)
            if changed == 0:
                await interaction.response.send_message(
                    "Te zadania są już odhaczone (albo nie istnieją).", ephemeral=True
                )
                return
            msg = f"✅ {interaction.user.mention} odhacza {changed} zadań!"
            if changed == 1:
                msg = f"✅ {interaction.user.mention} odhacza zadanie!"
            if minted:
                msg += f" (+{minted} {COINS_EMOJI})"
            # Public when coins flowed — celebrating progress is the house culture.
            await interaction.response.send_message(msg, ephemeral=not minted)
        except Exception as e:
            logger.error(f"Error in /todo zrobione: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="cofnij", description="Odznacz zadania z powrotem na otwarte")
    @app_commands.describe(numery="Numery z /todo lista, np. `2` albo `1,3-5`")
    async def cofnij(self, interaction: discord.Interaction, numery: str):
        try:
            ids = await self._resolve_indices(interaction, numery)
            if ids is None:
                return
            result = todo_set_done(str(interaction.user.id), ids, False)
            changed = (result or {}).get("changed", 0)
            await interaction.response.send_message(
                f"↩️ Odznaczono {changed} zadań." if changed else
                "Te zadania nie były odhaczone.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error in /todo cofnij: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="usun", description="Usuń zadania z listy (np. 2 albo 1,3-5 albo all)")
    @app_commands.describe(numery="Numery z /todo lista, np. `2` albo `1,3-5` albo `all`")
    async def usun(self, interaction: discord.Interaction, numery: str):
        try:
            ids = await self._resolve_indices(interaction, numery)
            if ids is None:
                return
            result = todo_remove(str(interaction.user.id), ids)
            removed = (result or {}).get("removed", 0)
            await interaction.response.send_message(
                f"🗑️ Usunięto {removed} zadań.", ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in /todo usun: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="wyczysc", description="Wyczyść całą listę zadań")
    async def wyczysc(self, interaction: discord.Interaction):
        try:
            items = todo_list(str(interaction.user.id))
            if not items:
                await interaction.response.send_message(
                    "Lista już jest pusta.", ephemeral=True
                )
                return
            todo_remove(str(interaction.user.id), [i["id"] for i in items])
            await interaction.response.send_message(
                f"🗑️ Wyczyszczono listę ({len(items)} zadań).", ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in /todo wyczysc: {e}")
            await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="edytuj", description="Zmień treść zadania")
    @app_commands.describe(numer="Numer z /todo lista", tresc="Nowa treść")
    async def edytuj(self, interaction: discord.Interaction, numer: int, tresc: str):
        tresc = tresc.strip()
        if not tresc or len(tresc) > TODO_MAX_CONTENT:
            await interaction.response.send_message(
                f"Treść musi mieć 1–{TODO_MAX_CONTENT} znaków.", ephemeral=True
            )
            return
        try:
            items = todo_list(str(interaction.user.id))
            if not (1 <= numer <= len(items)):
                await interaction.response.send_message(
                    f"Nie ma zadania numer {numer} — sprawdź `/todo lista`.",
                    ephemeral=True,
                )
                return
            result = todo_edit(str(interaction.user.id), items[numer - 1]["id"], tresc)
            if result and result.get("ok"):
                await interaction.response.send_message(
                    f"✏️ Zmieniono zadanie {numer}.", ephemeral=True
                )
            else:
                await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in /todo edytuj: {e}")
            await interaction.response.send_message(DB_ERROR_MSG, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Todo(bot))
