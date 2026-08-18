# Zakładki głosowe — słowo-klucz „Momentum" zaznacza fragmenty spotkania

## Kontekst

Ludwik chce zaznaczać ważne momenty spotkania głosem: gdy na nagraniu padnie
słowo-klucz, Momentum zapamiętuje ten moment; później można zapytać (konwersacyjnie,
przez przywołanie) „pokaż mi zaznaczone fragmenty", a Momentum poda **to, co było
przed słowem-kluczem** — przy czym to **model ma zdecydować**, jaki fragment ma sens
dla człowieka (zrozumieć kontekst, uciąć na naturalnej granicy wypowiedzi).

Ustalenia z Ludwikiem:
- **Słowo-klucz: „Momentum"** — świadomie, mimo że nazwa bota pada też w zwykłej
  rozmowie. Każde wypowiedzenie tworzy zakładkę; szum odsiewa model przy odczycie
  (markery, które są tylko luźną wzmianką o bocie, pomija).
- **Dostęp: każdy przez rozmowę** (nowe narzędzie w przywołaniach; bez komendy slash).

Fakty o kodzie (z eksploracji — kluczowe dla wykonawcy):

- `transcribe.transcribe_words(audio_path) -> (text, words)` (`transcribe.py:62`);
  każde słowo to dokładnie `{"word": str, "start": float, "end": float}` (sekundy od
  początku nagrania, budowane w linii 99). **Timestampy słów żyją tylko w pamięci** —
  `diarize()` je wyrzuca, nic ich nie persystuje. Detekcja musi więc zajść w oknie
  post-transkrypcja / pre-zapis, tj. w `voicerecord._build_transcript` (linia 599),
  przez które przechodzą OBA call-site'y (pipeline ~505 i recovery ~349).
- `transcribe.diarize(words, segments) -> str` (`transcribe.py:135`): skleja słowa w
  bloki `**Imię:** tekst` przez `_join_words` (linia 163), bloki rozdziela `\n\n`.
  Pseudo-słowo wstawione do listy `words` przepłynie przez `_join_words` nietknięte
  i wyląduje w tekście bloku właściwego mówcy (ten sam timestamp ⇒ ten sam mówca).
- Parsowanie transkryptów jest zakotwiczone na `^\*\*` (`transcripts._SPEAKER_RE`,
  linia 35) — marker **wewnątrz** tekstu bloku jest bezpieczny; na początku linii by
  zepsuł `extract_speakers`/`filter_by_speaker`.
- Narzędzia przywołań: rejestr `_TOOLS` (`cogs/przywolanie.py:313`, schematy
  Chat-Completions, opisy po polsku), dispatch `_run_tool(name, args) -> str`
  (linia 384, płaski if-chain, listy zwracane jako `json.dumps(..., ensure_ascii=False)`),
  mirror `_TOOLS_RESPONSES` liczy się sam (linia 450). Zbiór `_TRANSCRIPT_TOOLS`
  (linia 456) podbija budżet odpowiedzi do `MOMENTUM_TRANSCRIPT_MAX_TOKENS` (1500) —
  **nowe narzędzie trzeba tam dopisać**, inaczej działa na 1000.
- `transcripts.list_transcripts` zwraca meta z frontmattera (`transcripts.py:97+`);
  `read_transcript(id)` zwraca body (linia 157).

## Zmiany

### 1. `config.py` — blok zakładek (obok bloku MOMENTUM_*)

```python
# --- Zakładki głosowe (bookmarks): słowo-klucz na nagraniu zaznacza moment ---
BOOKMARK_ENABLED = True
BOOKMARK_KEYWORDS = ("momentum",)   # porównanie po normalizacji: lower + bez interpunkcji
BOOKMARK_MERGE_SECONDS = 60         # wystąpienia bliżej siebie łączą się w jedną zakładkę
BOOKMARK_MAX_PER_MEETING = 12       # cap markerów zwracanych narzędziu odczytu
BOOKMARK_CONTEXT_BEFORE_CHARS = 2500  # kontekst PRZED markerem podawany modelowi
BOOKMARK_CONTEXT_AFTER_CHARS = 400    # i chwila PO — model widzi, czy temat trwał dalej
```

### 2. Nowy czysty moduł `bookmarks.py` (stdlib-only, unit-testowalny)

Marker w tekście: `⟦ZAKŁADKA @ MM:SS⟧` (lub `H:MM:SS` powyżej godziny). Nawiasy
`⟦⟧` nie występują w mowie ani markdownie — regex jest jednoznaczny.

```python
MARKER_RE = re.compile(r"⟦ZAKŁADKA @ (\d{1,2}(?::\d{2}){1,2})⟧")

def fmt_time(seconds: float) -> str:
    """69.4 -> '1:09'; 3671 -> '1:01:11'."""

def normalize_word(w: str) -> str:
    """lower + zdejmij wszystko poza [a-z0-9ąćęłńóśźż] (Whisper dokleja interpunkcję)."""

def annotate_words(words: list[dict], *, keywords=BOOKMARK_KEYWORDS,
                   merge_seconds=BOOKMARK_MERGE_SECONDS) -> tuple[list[dict], list[float]]:
    """Wstaw pseudo-słowo markera PO każdym dopasowanym słowie-kluczu.

    Pseudo-słowo: {"word": "⟦ZAKŁADKA @ <fmt_time(t)>⟧", "start": t, "end": t}
    (t = start dopasowanego słowa). Dopasowanie w odległości < merge_seconds od
    ostatniego zaakceptowanego jest pomijane (anty-spam przy 'Momentum' padającym
    seriami). Zwraca (nową listę, listę czasów zakładek). Pure.
    """

def extract_marker_times(body: str) -> list[str]:
    """MARKER_RE.findall — czasy zakładek z gotowego body ('12:34', ...)."""

def context_windows(body: str, *, before=BOOKMARK_CONTEXT_BEFORE_CHARS,
                    after=BOOKMARK_CONTEXT_AFTER_CHARS,
                    max_markers=BOOKMARK_MAX_PER_MEETING) -> list[dict]:
    """Dla każdego markera w body: {'czas': 'MM:SS', 'kontekst': '…tekst…'}.

    Kontekst = body[max(0, i-before) : koniec_markera+after], z '…' na uciętych
    krawędziach. Powyżej max_markers — utnij i dodaj wpis
    {'uwaga': 'pominięto N dalszych zakładek'} na końcu listy. Pure.
    """
```

Domyślne wartości parametrów bierz z `config` na poziomie modułu (import jak w
`transcripts.py`) — testy nadpisują przez argumenty keyword-only.

### 3. `transcribe.py` — upublicznij join

Dodaj alias `join_words = _join_words` (jedna linia pod definicją, linia ~163) —
potrzebny w `_build_transcript` do odtworzenia plain-textu z adnotowanych słów,
gdy diarizacja nie zadziała.

### 4. `cogs/voicerecord.py::_build_transcript` (linia 599) — hak detekcji

Na samej górze funkcji, przed obecną logiką diarizacji:

```python
if BOOKMARK_ENABLED and words:
    try:
        words, _marks = bookmarks.annotate_words(words)
        if _marks:
            text = transcribe.join_words(words)  # markery także w plain-text fallbacku
    except Exception as e:
        logger.error("Bookmark detection failed: %s", e)  # nigdy nie blokuj pipeline'u
```

Dalej bez zmian — `diarize(words, segments)` dostaje już adnotowaną listę, więc
markery lądują w blokach właściwych mówców. Oba call-site'y (pipeline i recovery)
przechodzą przez tę funkcję — jeden hak wystarcza. Import `bookmarks` + stała z config.

### 5. `transcripts.py` — zakładki we frontmatterze i w liście

- `render_document` (ze speca 2026-08-18-drive-transcript-md-admin-lookup.md): po linii `uczestnicy:` dodaj — tylko gdy niepuste —
  `zakladki: 12:34, 25:10` (`", ".join(bookmarks.extract_marker_times(text))`).
- `list_transcripts`: do zwracanego dicta dodaj
  `"zakladki": [t.strip() for t in meta.get("zakladki", "").split(",") if t.strip()]`.
  Stare transkrypty bez pola → pusta lista (kompatybilne).

### 6. `cogs/przywolanie.py` — narzędzie `zakladki` + prompt

**Schemat** (append do `_TOOLS`, linia ~355, przed warunkowym `szukaj_w_bazie`):

```python
{
    "type": "function",
    "function": {
        "name": "zakladki",
        "description": (
            "Zaznaczone fragmenty spotkań (zakładki ⟦ZAKŁADKA⟧ — momenty, w których "
            "na nagraniu padło słowo „Momentum”). Bez 'id' zwraca listę spotkań z "
            "zakładkami; z 'id' zwraca kontekst rozmowy wokół każdej zakładki."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "id spotkania z lista_spotkan (opcjonalnie)"},
                "dni": {"type": "integer", "description": "ile dni wstecz szukać spotkań z zakładkami (domyślnie 30)"},
            },
        },
    },
},
```

**Dispatch** (gałąź w `_run_tool`, linia ~384, wzorzec jak `czytaj_spotkanie`):

- bez `id`: `list_transcripts(within_days=min(int(dni or 30), 90))`, przefiltruj do
  `m["zakladki"]`, zwróć `json.dumps([{id, data, kanal, zakladki}, ...], ensure_ascii=False)`;
  pusto → `"Brak spotkań z zakładkami w tym okresie."`
- z `id`: `body = transcripts.read_transcript(id)`; brak → `"Nie znam spotkania o id …"`;
  `wins = bookmarks.context_windows(body)`; pusto → `"To spotkanie nie ma zakładek."`;
  inaczej `json.dumps(wins, ensure_ascii=False)`.

**Budżet**: `_TRANSCRIPT_TOOLS = {"lista_spotkan", "czytaj_spotkanie", "zakladki"}`
(linia 456) — odpowiedź z fragmentami dostaje 1500 tokenów.

**SYSTEM_PROMPT** — nowa krótka sekcja (obok istniejących zasad transkryptów):

```
ZAKŁADKI: uczestnicy zaznaczają ważne momenty spotkania, wypowiadając słowo
„Momentum" — w transkrypcie to marker ⟦ZAKŁADKA @ czas⟧. Gdy ktoś prosi o
„zaznaczone fragmenty", użyj narzędzia zakladki. Dla każdej zakładki sam oceń,
co jest istotą zaznaczonego momentu: z reguły to wypowiedź BEZPOŚREDNIO
POPRZEDZAJĄCA marker — zacytuj ją lub streść, ucinając na naturalnej granicy
(początek myśli, nie środek zdania), z czasem i autorem. Markery będące tylko
luźną wzmianką o bocie (np. rozmowa o samym Momentum) pomiń i powiedz, że je
pominąłeś. Jeśli marker jest na samym początku kontekstu, podaj to, co PO nim.
```

### 7. Testy — `tests/test_bookmarks.py` (+ drobne w `test_transcripts.py`)

- `fmt_time`: 0, 69.4, 3671.
- `normalize_word`: `"Momentum,"` → `"momentum"`, `"„Momentum”."` → `"momentum"`.
- `annotate_words`: dopasowanie wstawia marker PO słowie z poprawnym czasem;
  merge window (dwa „momentum" w 10 s → jeden marker; po 61 s → dwa); brak
  dopasowań → lista wraca niezmieniona (`marks == []`); słowa niedotknięte.
- `extract_marker_times` + `context_windows`: pozycje, `…` przy ucięciu, cap
  `max_markers` z wpisem `uwaga`.
- `test_transcripts.py`: `render_document` z markerem w body → frontmatter ma
  `zakladki:`; bez markera → brak linii; `list_transcripts` parsuje pole.

### 8. Dokumentacja + git

- `CLAUDE.md`: tabela config (blok `BOOKMARK_*`), wiersz `przywolanie` w tabeli cogów
  (dopisek o zakładkach), changelog 2026-08. Spec →
  `docs/superpowers/specs/2026-08-18-voice-bookmarks-design.md`. Commit + push na main.

## Zależność i weryfikacja

**Kolejność: najpierw spec `2026-08-18-drive-transcript-md-admin-lookup.md`** (wprowadza `render_document`, na którym wisi pkt 5).
Markery automatycznie trafią też do plików `-transcript.md` na Drive (wspólny renderer).
Stare transkrypty nie mają markerów — narzędzie `zakladki` po prostu ich nie wylistuje.

1. `python3 -m unittest discover tests` + `py_compile` zmienionych plików.
2. Deploy wg CLAUDE.md; w journalctl bez tracebacków.
3. E2E: krótkie nagranie testowe (`/nagraj`, 2 osoby lub obniżony próg), powiedz w
   trakcie „Momentum" → po stopie sprawdź w `transcripts/*.md` marker
   `⟦ZAKŁADKA @ …⟧` i linię `zakladki:` we frontmatterze; potem na kanale tekstowym:
   „Momentum, pokaż zaznaczone fragmenty z dzisiaj" → odpowiedź z czasem, autorem
   i sensownym fragmentem sprzed markera.

---

## Rekomendacja modelu do implementacji

**Sonnet 5, effort high.** Oba specy z 2026-08-18 są rozpisane prescriptywnie (sygnatury,
call-site'y z numerami linii, schematy narzędzi, teksty promptów), więc Opus/Fable to
nadmiar. Effort high zamiast medium przez ten spec: styk z pętlą tool-callingu w
`przywolanie.py` (rejestr + dispatch + budżety tokenów) i hak w delikatnym pipeline
nagrań — oba miejsca mają wzorce do skopiowania, ale błąd integracyjny objawia się
dopiero w runtime na produkcji. Haiku odpada (discord.py + OpenAI tool-calling +
realne API Drive). Jeśli implementujesz specy w dwóch osobnych sesjach: drive-transcript-md — Sonnet 5
medium, zakładki — Sonnet 5 high.
