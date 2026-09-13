import logging

import discord
from discord.ext import commands

from config import EMBED_FIX_ENABLED, EMBED_FIX_HOSTS, EMBED_FIX_IGNORED_CHANNEL_IDS
from parsers import rewrite_bare_social_link

logger = logging.getLogger("momentum_bot.embed_fix")

# Maskowany link: widoczny jest tylko dwukropek, a podgląd i tak się renderuje
# (sprawdzone na żywo 13.09.2026 — Discord zwraca embed typu "video" zarówno dla
# gołego URL-a, jak i dla tej formy). Czytelniejsze niż wklejanie długiego adresu
# drugi raz pod wiadomością użytkownika.
_REPLY_TEMPLATE = "Przesyłam zawartość linku[:]({url})"

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
        # Kanały, na których wysyłka dostała 403 — ostrzegamy raz, zamiast przy
        # każdym linku. Uprawnienia są PER KANAŁ, więc jeden zamknięty kanał nie
        # może wyłączyć feature'u wszędzie. In-memory, zeruje się przy restarcie
        # (wzorzec: _offer_last w przywolanie.py).
        self._send_denied: set[int] = set()
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
            return  # w DM z botem nie ma czego poprawiać
        if message.channel.id in EMBED_FIX_IGNORED_CHANNEL_IDS:
            return
        if message.attachments or message.stickers:
            return  # nie mieszamy się w wiadomości z mediami (por. photo_reply)
        if message.flags.suppress_embeds:
            return  # autor sam wyłączył podgląd — szanujemy to

        fixed = rewrite_bare_social_link(message.content, hosts=EMBED_FIX_HOSTS)
        if not fixed:
            return
        content = _REPLY_TEMPLATE.format(url=fixed)
        if len(content) > 2000:
            return

        # Wiadomość autora zostaje NIETKNIĘTA — nie kasujemy jej i nie gasimy jej
        # embedu. Bot potrafiłby ustawić SUPPRESS_EMBEDS na cudzej wiadomości
        # (ma ADMINISTRATOR), ale świadomie tego nie robi: modyfikowanie cudzych
        # wiadomości jest inwazyjne, a przy linkach do Instagrama natywny podgląd
        # i tak się nie renderuje, więc nie ma czego gasić.
        #
        # Osobna wiadomość zamiast reply: podgląd ma stać sam, bez dymka
        # "w odpowiedzi na", który przy każdym linku dokładał szumu.
        try:
            await message.channel.send(content, allowed_mentions=_NO_PINGS)
        except discord.Forbidden:
            # Brak prawa pisania na tym kanale — nie ma sensu ponawiać, ale
            # logujemy raz per kanał, żeby nie zalać logu przy każdym linku.
            if message.channel.id not in self._send_denied:
                self._send_denied.add(message.channel.id)
                logger.warning(
                    "Brak prawa pisania na kanale %s — pomijam poprawianie linków "
                    "tutaj do restartu.", message.channel.id,
                )
        except discord.HTTPException as e:
            logger.warning(
                "Nie udało się wysłać poprawionego linku na kanale %s: %s",
                message.channel.id, e,
            )
        except Exception as e:
            logger.error("Błąd w embed_fix.on_message: %s", e)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedFix(bot))
