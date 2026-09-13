import logging

import discord
from discord.ext import commands

from config import EMBED_FIX_ENABLED, EMBED_FIX_HOSTS, EMBED_FIX_IGNORED_CHANNEL_IDS
from parsers import rewrite_bare_social_link

logger = logging.getLogger("momentum_bot.embed_fix")

# Odpowiedź to goły URL, ale ŚCIEŻKA może zawierać dosłowne "@everyone"
# (https://x.com/status/@everyone) — Discord parsuje wzmianki po samym tekście.
# main.py tworzy Bota BEZ allowed_mentions, więc domyślne mają everyone=True,
# a bot ma realne MENTION_EVERYONE (daily_invite.py wysyła @here). Bez tego
# każdy mógłby przez bota pingnąć serwer. Świadome odstępstwo od
# _REPLY_MENTIONS z przywolanie.py — tam users=True jest potrzebne, tu nie
# pingujemy NIKOGO.
_NO_PINGS = discord.AllowedMentions.none()


class EmbedFix(commands.Cog):
    """Goły link do social mediów → odpowiedź na domenie z działającym podglądem."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Kanały, gdzie edycja cudzej wiadomości dostała 403 — nie ponawiamy i
        # ostrzegamy raz. Uprawnienia są PER KANAŁ, więc jeden zamknięty kanał
        # nie może wyłączyć wygaszania wszędzie. In-memory, zeruje się przy
        # restarcie (wzorzec: _offer_last w przywolanie.py).
        self._suppress_denied: set[int] = set()
        logger.info("EmbedFix cog initialized")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Nigdy nie reagujemy na siebie ani na inne boty/webhooki. Drugą,
        # niezależną warstwą jest to, że hosty DOCELOWE nie są kluczami w
        # EMBED_FIX_HOSTS — już naprawiony link nie matchuje, nawet gdyby ten
        # guard kiedyś zniknął.
        if message.author.bot:
            return
        if not EMBED_FIX_ENABLED:
            return
        if message.guild is None:
            return  # DM: nie ma manage_messages, edit i tak zwróciłby 403
        if message.channel.id in EMBED_FIX_IGNORED_CHANNEL_IDS:
            return
        if message.attachments or message.stickers:
            return  # nie mieszamy się w wiadomości z mediami (por. photo_reply)
        if message.flags.suppress_embeds:
            return  # autor sam wyłączył podgląd — szanujemy to

        fixed = rewrite_bare_social_link(message.content, hosts=EMBED_FIX_HOSTS)
        if not fixed or len(fixed) > 2000:
            return

        # Kolejność: NAJPIERW odpowiedź, POTEM wygaszenie. Odwrotna jest
        # ładniejsza (flaga wyprzedza unfurler Discorda, oryginalny embed w ogóle
        # się nie renderuje), ale gdy wysyłka padnie, zostawia użytkownika bez
        # podglądu i bez odpowiedzi. Nigdy nie kasujemy, zanim nie damy zamiennika.
        try:
            await message.reply(fixed, mention_author=False, allowed_mentions=_NO_PINGS)
        except discord.HTTPException as e:
            # m.in. wiadomość skasowana w międzyczasie (400 na reference) albo
            # brak prawa pisania. Nic nie wygaszamy — oryginał zostaje nietknięty.
            logger.warning(
                "Nie udało się odpowiedzieć poprawionym linkiem na kanale %s: %s",
                message.channel.id, e,
            )
            return
        except Exception as e:
            logger.error("Błąd w embed_fix.on_message (odpowiedź): %s", e)
            return

        if message.channel.id in self._suppress_denied:
            return
        try:
            # Edytujemy CUDZĄ wiadomość, ale payload to wyłącznie flags — na to
            # wystarcza "Zarządzanie wiadomościami" (w wątku/forum liczone z kanału
            # nadrzędnego). Świadomie bez pre-checku permissions_for: na Thread
            # rzuca ClientException, gdy rodzic nie jest w cache.
            await message.edit(suppress=True)
        except discord.Forbidden:
            self._suppress_denied.add(message.channel.id)
            logger.warning(
                "Brak uprawnienia 'Zarządzanie wiadomościami' na kanale %s — "
                "oryginalny podgląd zostaje obok poprawionego linku. "
                "Nie ponawiam do restartu.",
                message.channel.id,
            )
        except discord.NotFound:
            pass  # autor skasował wiadomość, zanim zdążyliśmy wygasić embed
        except Exception as e:
            logger.error("Błąd w embed_fix.on_message (wygaszenie): %s", e)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedFix(bot))
