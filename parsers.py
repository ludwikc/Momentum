"""Pure input parsers for the StudyLion-port features (reminders, todo).

No discord/pytz imports on purpose: everything here is unit-tested with the
system Python (tests/test_parsers.py). Timezone handling stays in the cogs.
"""
import re
from datetime import datetime, timedelta
from typing import Optional

# One duration token: an amount + a unit. Longer unit words must precede their
# prefixes (e.g. "dni" before "d") because regex alternation is first-match.
_DURATION_TOKEN = re.compile(
    r"(\d+)\s*(dni|dzień|dzien|d|godzin\w*|godz|h|minut\w*|min|m|sekund\w*|sek|s)",
    re.IGNORECASE,
)

# First letter of the (Polish or short) unit → seconds. g = godziny.
_UNIT_SECONDS = {"d": 86400, "g": 3600, "h": 3600, "m": 60, "s": 1}

_ALL_KEYWORDS = {"all", "-", "wszystkie", "wszystko"}

_CLOCK_RE = re.compile(r"^(\d{1,2})[:.](\d{2})$")

_FRACTION_RE = re.compile(r"\.(\d{1,6})")


def parse_db_timestamp(value: str) -> datetime:
    """PostgREST timestamptz JSON → aware datetime.

    Postgres trims trailing zeros in fractional seconds (".5", ".1234"), which
    Python 3.10's fromisoformat rejects (it wants exactly 3 or 6 digits) — pad
    the fraction to 6 digits and normalize a Z suffix.
    """
    value = value.replace("Z", "+00:00")
    value = _FRACTION_RE.sub(lambda m: "." + m.group(1).ljust(6, "0"), value, count=1)
    return datetime.fromisoformat(value)


def parse_duration_pl(text: str) -> int | None:
    """Parse "3h", "1d 2h 30m", "10 minut" etc. into seconds.

    A bare integer is interpreted as minutes (mirrors StudyLion's slash-command
    convention). Returns None when the text isn't a valid duration.
    """
    text = (text or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text) * 60

    total = 0
    pos = 0
    matched = False
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        m = _DURATION_TOKEN.match(text, pos)
        if not m:
            return None
        amount, unit = int(m.group(1)), m.group(2).lower()
        total += amount * _UNIT_SECONDS[unit[0]]
        matched = True
        pos = m.end()
    return total if matched else None


def parse_wallclock_pl(text: str, now: datetime) -> datetime | None:
    """Parse "16:00", "16.30", "2026-07-12 09:30" or "2026-07-12" into a naive
    datetime in the same (naive) frame as `now`.

    A bare time that is not in the future rolls over to tomorrow. Returns None
    on anything unparseable.
    """
    text = (text or "").strip()
    if not text:
        return None

    m = _CLOCK_RE.match(text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour > 23 or minute > 59:
            return None
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_profile_tags(text: str, max_tags: int, max_len: int) -> list[str] | None:
    """Parse the /profil tag input: `;`-separated, trimmed, empties dropped,
    case-insensitive dedupe keeping the first spelling.

    Empty input means "clear tags" → []. Returns None when a tag exceeds
    max_len or more than max_tags remain (caller shows the error).
    """
    pieces = [p.strip() for p in (text or "").split(";")]
    tags: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        if not piece:
            continue
        if len(piece) > max_len:
            return None
        key = piece.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(piece)
    if len(tags) > max_tags:
        return None
    return tags


def parse_index_ranges(text: str, max_index: int) -> list[int] | None:
    """Parse "1", "1,3", "2-5", "1, 3-4, 8" or all/-/wszystkie into a sorted,
    de-duplicated list of 1-based indices.

    Returns None when any token is invalid or out of 1..max_index (mirrors
    StudyLion's strict range parsing).
    """
    text = (text or "").strip().lower()
    if not text:
        return None
    if text in _ALL_KEYWORDS:
        return list(range(1, max_index + 1))

    indices: set[int] = set()
    for token in text.split(","):
        token = token.strip()
        if re.fullmatch(r"\d+", token):
            start = end = int(token)
        else:
            m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
            if not m:
                return None
            start, end = int(m.group(1)), int(m.group(2))
            if start > end:
                return None
        if start < 1 or end > max_index:
            return None
        indices.update(range(start, end + 1))
    return sorted(indices)


# Link do wiadomości Discord: /channels/<guild>/<channel>/<message>. Warianty
# subdomen (ptb., canary.) i stara domena discordapp.com też przechodzą.
# Linki DM (/channels/@me/...) celowo NIE matchują — guild musi być liczbą.
_MESSAGE_LINK_RE = re.compile(
    r"https?://(?:\w+\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)"
)


def parse_message_link(text: str) -> tuple[int, int, int] | None:
    """Pierwszy link do wiadomości Discord w ``text`` → (guild_id, channel_id,
    message_id), albo None gdy linku brak."""
    m = _MESSAGE_LINK_RE.search(text or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


_RECORDING_FILENAME_RE = re.compile(
    r"^Lifehackerzy_(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})_(.+)_([0-9a-f]{6})\.(wav|mp3)$"
)


def parse_recording_filename(name: str) -> Optional[tuple[datetime, str, str]]:
    """Split a recorder filename into (started, channel_slug, rec_id).

    The voice recorder names files
    ``Lifehackerzy_<YYYY-MM-DD-HH-MM-SS>_<slug>_<rec_id>.wav`` (Warsaw-local
    clock). Anything else — legacy files, diarization sidecars — returns None.
    Slugs never contain underscores (see voicerecord.slug_channel_name), so the
    greedy middle group cannot swallow the rec_id.
    """
    m = _RECORDING_FILENAME_RE.match(name or "")
    if not m:
        return None
    try:
        started = datetime.strptime(m.group(1), "%Y-%m-%d-%H-%M-%S")
    except ValueError:
        return None
    return started, m.group(2), m.group(3)
