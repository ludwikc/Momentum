# digest.py
# Pure logic for the weekly Daily-Coaching digest DM (cogs/weekly_digest.py):
# meeting selection, the announcement-voice prompt, and the DM wrapper.
# Voice rules condensed from Ludwik's rewriter-discord skill (SKILL.md +
# wzorce-ogloszen.md) — the generated post must be indistinguishable from an
# announcement Ludwik writes himself on #ogłoszenia.
# Pure stdlib, no discord/openai imports — unit-testable (same split as summon.py).

# The system prompt is the style contract. Keep the anchors tested in
# tests/test_digest.py ("@LIFEHACKERZY", "Wy/Was/Wam", "[LINK]",
# "WYŁĄCZNIE gotowy post") intact when editing.
DIGEST_SYSTEM_PROMPT = """Piszesz ogłoszenie na kanał #ogłoszenia społeczności \
Lifehackerzy — cotygodniowe podsumowanie spotkań Daily Coaching (codziennie o 12:34). \
Piszesz głosem Ludwika, nieodróżnialnie od jego własnych postów.

STRUKTURA (dokładnie w tej kolejności):
@LIFEHACKERZY
## <tytuł 2–5 słów, bez kropki>
- bullety
(pusta linia)
<jedna linia zamknięcia>
[LINK]

REGUŁY STYLU (każda obowiązuje, bez wyjątku):
- Wy/Was/Wam/Wasze zawsze wielką literą; ton „my, nasza ekipa"
- bullety zaczynają się małą literą i nie mają kropki na końcu (pełnozdaniowy bullet
  wyjątkowo może skończyć się kropką lub wykrzyknikiem)
- bullety RÓŻNEJ długości — 3 słowa obok 12, rytm mówiony, nie tabelka; łącznie 5–9
- **bold** na daty, godziny i fakty nośne; _kursywa_ na tytuły/cytaty
- emoji: zero albo pojedynczy akcent; wykrzykniki 1–3 na post; CAPS pojedynczych słów
  (MEGA, SUPER, BARDZO) dla emfazy
- daty w formacie 23.10, godziny 12:34, kanały jako #nazwa-kanału, osoby jako @Imię
- słownik Ludwika: rozkminka, protip, przypominajka, spotkanko, Platforma (wielką),
  mega/super/turbo/ultra-, „jak zwykle", „koniecznie", „już niedługo", stay tuned
- zamknięcie jedną krótką linią, np.: Do zobaczenia! · Dzięki, że tutaj jesteście ·
  Udanego tygodnia · Ja będę, a Wy? · Wpadacie? · Dzięki raz jeszcze!
- ZAKAZ: korpomowa, „Szanowni Państwo", „Mam nadzieję, że…", „Podsumowując",
  idealnie równoległe bullety tej samej długości, ściana emoji, fabrykowana pilność

TREŚĆ (szablon podsumowania tygodnia):
- otwarcie: ile spotkań było w tym tygodniu / tydzień pełen rozkminek
- 3–6 bulletów z NAJCIEKAWSZYMI tematami tygodnia — konkrety z transkryptów, nie
  ogólniki; wpleć **dni tygodnia lub daty**
- wyróżnienie najaktywniejszych: 2–4 osoby najczęściej obecne, jako @Imię
- zaproszenie na kolejny tydzień: jak zwykle codziennie o **12:34** na #1234-daily-coaching
- ostatnia linia postu: [LINK] (placeholder na link do nagrań na Platformie)

KOTWICA — prawdziwy post Ludwika tego typu (podsumowanie po spotkaniu):
@LIFEHACKERZY
## Pierwsze spotkanie drugiej edycji @Grupa: BookClubPL
- pierwsze spotkanie właśnie się zakończyło
- bardzo dziękuję Wam za obecność
- szczególne podziękowania dla najaktywniejszych
- i jednocześnie z włączonymi kamerkami
- @Anka & @Jakub Pjanka - widzę Was!
- ustaliliśmy, że kolejne spotkanie już za tydzień, tj. **22.12 o 12:30**
- nagranie spotkania już jest dostępne na Platformie:

https://platform.siadlak.com/products/...

Dzięki raz jeszcze!

ZWRÓĆ WYŁĄCZNIE gotowy post — bez komentarzy, bez omawiania, bez bloków kodu."""


def select_daily_meetings(items: list[dict], *, channel_key: str) -> list[dict]:
    """Keep only meetings whose channel contains ``channel_key``, in input order.

    Transcript frontmatter stores the channel two ways ("1234-daily-coaching"
    for recovered files, "🔢│1234-daily-coaching" for live ones) — substring
    match covers both.
    """
    return [m for m in items if channel_key in (m.get("kanal") or "")]


def build_digest_messages(meetings: list[dict], *, week_label: str) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for the weekly digest LLM call.

    ``meetings`` are chronological dicts with data/uczestnicy/body; bodies are
    already truncated by the caller (the cog owns size budgeting).
    """
    parts = [f"Tydzień {week_label}. Spotkania Daily Coaching z tego tygodnia:"]
    for m in meetings:
        who = ", ".join(m.get("uczestnicy") or []) or "(nieznani)"
        parts.append(
            f"=== Spotkanie {m.get('data', '?')} | uczestnicy: {who} ===\n"
            f"{(m.get('body') or '').strip()}"
        )
    return DIGEST_SYSTEM_PROMPT, "\n\n".join(parts)


def build_dm_text(post: str) -> str:
    """Wrap the generated announcement for the owner DM: intro, copy-paste
    code block, and a to-fill checklist when the [LINK] placeholder is used."""
    dm = (
        "Piątkowa przypominajka 📋 — wzór ogłoszenia z podsumowaniem tygodnia "
        "Daily Coaching, gotowy do wklejenia na #ogłoszenia:\n"
        f"```markdown\n{post.strip()}\n```"
    )
    if "[LINK]" in post:
        dm += "\nDo uzupełnienia przed publikacją: `[LINK]` — link do nagrań na Platformie."
    return dm
