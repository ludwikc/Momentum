import discord
from config import ACTIVITIES, COINS_EMOJI

# Discord renders up to 3 inline fields per row. To force a clean 2-column grid
# we drop an invisible field as the 3rd cell of every row so the next tile wraps.
# ``​`` (zero-width space) is Discord's canonical "empty" name/value — a
# field value must be non-empty, so this is the minimal legal filler.
_ZW = "​"
_DIVIDER = "─" * 15


def _plural_pl(n: int, one: str, few: str, many: str) -> str:
    """Polish plural selection (e.g. godzina/godziny/godzin)."""
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many


def format_duration_pl(seconds: int) -> str:
    """Format a duration in seconds as Polish 'X godzin i Y minut'."""
    minutes_total = max(seconds, 0) // 60
    hours = minutes_total // 60
    minutes = minutes_total % 60
    h_word = _plural_pl(hours, "godzina", "godziny", "godzin")
    m_word = _plural_pl(minutes, "minuta", "minuty", "minut")
    if hours > 0 and minutes > 0:
        return f"{hours} {h_word} i {minutes} {m_word}"
    if hours > 0:
        return f"{hours} {h_word}"
    return f"{minutes} {m_word}"


def _deep_work_text(stats: dict) -> str:
    """'14 godzin i 30 minut (22 sesje)' from the stats dict, or '' if no Deep
    Work has been banked yet."""
    dw_sessions = stats.get("total_deep_work", 0)
    dw_seconds = stats.get("deep_work_seconds", 0)
    if dw_sessions <= 0 and dw_seconds <= 0:
        return ""
    sessions_text = ""
    if dw_sessions > 0:
        word = _plural_pl(dw_sessions, "sesja", "sesje", "sesji")
        sessions_text = f"{dw_sessions} {word}"
    if dw_seconds > 0 and sessions_text:
        return f"{format_duration_pl(dw_seconds)} ({sessions_text})"
    if dw_seconds > 0:
        return format_duration_pl(dw_seconds)
    return sessions_text


def _hero_tiles(stats: dict, hero_key):
    """Build the prominent hero tile(s) for the event that triggered the card.

    Returns ``(tiles, consumed)`` where ``tiles`` is a list of ``(name, value)``
    inline fields and ``consumed`` is the set of stat keys those tiles represent
    (dropped from the grid below so nothing is shown twice). Falls back to no
    hero — ``([], set())`` — whenever the underlying stat is zero/absent (e.g.
    the extended stats RPC isn't applied yet), so the headline still stands alone
    and the grid stays correct.
    """
    if hero_key == "deep_work":
        dw_sessions = stats.get("total_deep_work", 0)
        dw_seconds = stats.get("deep_work_seconds", 0)
        if dw_sessions <= 0 and dw_seconds <= 0:
            return [], set()
        tiles = []
        if dw_seconds > 0:
            tiles.append(("⏱️ Łączny czas", f"**{format_duration_pl(dw_seconds)}**"))
        if dw_sessions > 0:
            tiles.append(("📈 Sesje ogółem", f"**{dw_sessions}**"))
        return tiles, {"deep_work"}

    if hero_key == "daily_coaching":
        c = stats.get("total_daily_coaching", 0)
        if c <= 0:
            return [], set()
        return [("🔢 Daily Coaching", f"**{c}**")], {"daily_coaching"}

    if hero_key in ACTIVITIES:
        count = stats.get(f"total_{hero_key}", stats.get(f"streak_{hero_key}", 0))
        if count <= 0:
            return [], set()
        emoji = ACTIVITIES[hero_key]
        return [(f"{emoji} {hero_key.capitalize()}", f"**{count}**")], {hero_key}

    return [], set()


def _grid_tiles(stats: dict, skip: set):
    """All non-zero lifetime stats as ``(name, value)`` tiles, in a stable order,
    excluding any key already surfaced as a hero tile (``skip``)."""
    tiles = []
    for name, emoji in ACTIVITIES.items():
        if name in skip:
            continue
        count = stats.get(f"total_{name}", stats.get(f"streak_{name}", 0))
        if count > 0:
            tiles.append((f"{emoji} {name.capitalize()}", f"**{count}**"))

    if "daily_coaching" not in skip:
        coaching_count = stats.get("total_daily_coaching", 0)
        if coaching_count > 0:
            tiles.append(("🔢 Daily Coaching", f"**{coaching_count}**"))

    if "deep_work" not in skip:
        dw_text = _deep_work_text(stats)
        if dw_text:
            tiles.append(("⚓️ Deep Work", f"**{dw_text}**"))

    voice_seconds = stats.get("voice_seconds_total", 0)
    if voice_seconds > 0:
        tiles.append(("🎙️ Na głosowych", f"**{format_duration_pl(voice_seconds)}**"))

    tasks_done = stats.get("tasks_done_total", 0)
    if tasks_done > 0:
        tiles.append(("✅ Zadania", f"**{tasks_done}**"))

    coins = stats.get("coins", 0)
    if coins > 0:
        tiles.append((f"{COINS_EMOJI} Monety", f"**{coins}**"))

    return tiles


def _add_grid(embed: discord.Embed, tiles) -> None:
    """Add tiles as a forced 2-column grid: two real inline fields per row, then
    an invisible inline field so Discord wraps instead of packing a 3rd tile."""
    for i, (name, value) in enumerate(tiles):
        embed.add_field(name=name, value=value, inline=True)
        if i % 2 == 1:
            embed.add_field(name=_ZW, value=_ZW, inline=True)


def build_progress_embed(user, headline, all_stats, *, hero_key=None):
    """Build the unified "Aktywność" card: a bold event headline, one or two
    prominent hero tiles for what just happened (``hero_key``), then the user's
    remaining lifetime counters as a 2-column grid.

    ``hero_key`` names the stat to elevate: ``"deep_work"``, ``"daily_coaching"``
    or any ``ACTIVITIES`` key (trening/medytacja/sukces/dziennik). Unknown/None →
    no hero tiles, just the headline over the full grid. Zero rows are always
    omitted; the Daily Coaching / Deep Work / StudyLion rows also stay hidden
    until the extended get_user_activity_stats RPC returns them.
    """
    embed = discord.Embed(title="Aktywność", color=0x280586)
    if headline:
        embed.description = f"**{headline}**"

    avatar = user.avatar or user.default_avatar
    embed.set_thumbnail(url=avatar.url)

    stats = all_stats or {}

    hero, consumed = _hero_tiles(stats, hero_key)
    for name, value in hero:
        embed.add_field(name=name, value=value, inline=True)

    tiles = _grid_tiles(stats, consumed)

    # A full-width divider separates the hero from the grid only when both exist;
    # inline=False guarantees it (and the grid after it) starts on a fresh row.
    if hero and tiles:
        embed.add_field(name=_ZW, value=_DIVIDER, inline=False)

    _add_grid(embed, tiles)
    return embed


def build_activity_embed(user, activity_type, result, all_stats):
    """Progress card for a self-reported activity: headline shows the monthly
    count and, when the consecutive-day streak exceeds 2, "(N z rzędu!)". The
    activity itself becomes the card's hero tile."""
    streak_count = result.get("streak_count", 1)
    consecutive = result.get("consecutive_count", 0)

    headline = f"🔥 To {streak_count} {activity_type} w tym miesiącu!"
    if consecutive > 2:
        headline += f" ({consecutive} z rzędu!)"

    return build_progress_embed(user, headline, all_stats, hero_key=activity_type)
