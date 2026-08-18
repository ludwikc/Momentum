# Transkrypty jako Markdown na Google Drive + `/admin transkrypt` (lookup po dacie)

## Kontekst

Pipeline nagrań zapisuje dziś transkrypt **lokalnie** jako pełny markdown z frontmatterem
(`transcripts/<YYYY-MM-DD_HH-MM>_<slug>_<recid>.md`, patrz `transcripts.save_transcript`),
ale na Google Drive wysyła go jako goły `.txt` obok MP3
(`cogs/voicerecord.py::_upload_transcript`, ~linia 625). Ludwik chce:

1. **Kompletny transkrypt jako plik markdown na Drive**, obok audio, ta sama nazwa
   z sufiksem `-transcript.md` — czyli `Lifehackerzy_<YYYY-MM-DD-HH-MM-SS>_<slug>_<recid>-transcript.md`.
2. **Komendę dla administratora**, która na żądanie poda link do transkryptu spotkania
   z danej daty. Ustalono z Ludwikiem: grupa **`/admin`** z podkomendą **`transkrypt`**
   (`/admin transkrypt data:<data>`), uprawnienie: Discordowy **Administrator**.
3. **Backfill** (ustalone: TAK) — jednorazowy skrypt wgrywający zaległe lokalne `.md`
   (pełna historia od 2026-06-25 w `transcripts/`) na Drive pod nową nazwą.

Fakty o kodzie, z których korzysta plan:

- Nazwa audio: `Lifehackerzy_<ts>_<slug>_<rec_id>` — `ts = %Y-%m-%d-%H-%M-%S` (Warsaw),
  patrz `voicerecord.py::_start` ~linia 166–169; parser istnieje:
  `parsers.parse_recording_filename(name) -> (started, slug, rec_id) | None` (linia 175).
- Lokalny stem transkryptu ma format `%Y-%m-%d_%H-%M_<slug>_<rec_id>` — **bez sekund**,
  więc backfill musi odnaleźć nazwę audio na Drive po `rec_id`, nie odtwarzać jej z stemu.
- `gdrive.upload_file(local_path, name, mime_type)` — blocking, wołane przez
  `asyncio.to_thread`; scope `drive.file` (SA widzi tylko pliki, które sam utworzył — to
  wystarcza do wyszukiwania, bo wszystkie nagrania wgrywa ten sam SA).
- `_upload_transcript` ma **2 call-site'y**: pipeline publikacji (~linia 530, zmienne w
  zasięgu: `transcript`, `started`, `rec_id`, `channel_name`) i recovery sierot
  (~linia 407, zmienne: `transcript`, `started`, `channel_slug`, `rec_id`).
- Wzorzec uprawnień: `/nagraj` używa `@app_commands.default_permissions(...)` +
  `@app_commands.checks.has_permissions(...)`; tu analogicznie z `administrator=True`.
- Konwencja repo: czyste helpery w modułach root + testy stdlib-unittest w `tests/`
  (`python3 -m unittest discover tests`).

## Zmiany

### 1. `transcripts.py` — wydziel czysty renderer dokumentu

Nowa funkcja (nad `save_transcript`):

```python
def render_document(text: str, *, started: datetime, channel_name: str, rec_id: str) -> str:
    """Full transcript document (frontmatter + diarized body) as written to disk.

    Returns "" for empty/whitespace text. Pure — shared by save_transcript and
    the Drive upload so both copies are byte-identical.
    """
```

Ciało: dokładnie to, co dziś buduje `save_transcript` (stem `%Y-%m-%d_%H-%M` + `_slug()`
+ `rec_id`, frontmatter `data/kanal/uczestnicy/id` z `extract_speakers`, potem
`text.strip() + "\n"`). `save_transcript` refaktoryzuje się do:
zbuduj `doc = render_document(...)`; jeśli puste → `return None`; zapisz `doc` do pliku.
Ścieżka/stem liczone tak jak dziś (stem można wyliczać raz i współdzielić wewnątrz modułu —
np. mały helper `_stem(started, channel_name, rec_id)` używany przez obie funkcje).

### 2. `cogs/voicerecord.py` — markdown na Drive zamiast `.txt`

`_upload_transcript` (~linia 625) zmienia sygnaturę i zawartość:

```python
async def _upload_transcript(self, mp3_path: str, document: str):
    """Write the transcript markdown next to the audio and upload it to Drive."""
    md_path = (mp3_path[:-4] if mp3_path.endswith(".mp3") else mp3_path) + "-transcript.md"
```

- zapis `document` do `md_path`, upload przez
  `gdrive.upload_file(md_path, os.path.basename(md_path), "text/markdown")`,
  `finally: os.remove(md_path)` — struktura try/except/finally bez zmian.

Call-site'y budują dokument przez wspólny renderer:

- **pipeline publikacji** (~linia 529–530):
  ```python
  if transcript:
      doc = (transcripts.render_document(transcript, started=started,
                                         channel_name=channel_name, rec_id=rec_id)
             if started is not None and rec_id is not None else transcript)
      await self._upload_transcript(mp3_path, doc)
  ```
  (guard `started/rec_id is not None` — ten sam, którym objęte jest `save_transcript`
  kilka linii wyżej; fallback = goły transkrypt, lepszy niż nic).
- **recovery** (~linia 406–407): analogicznie, z `channel_name=channel_slug`
  (tak samo jak istniejące wywołanie `save_transcript` w recovery).

### 3. `gdrive.py` — wyszukiwanie po nazwie

Nowa funkcja pod `upload_file`:

```python
def find_files(name_contains: str, *, page_size: int = 50) -> list[dict]:
    """Files in Drive whose name contains the substring (only files this SA created).

    Blocking — call via asyncio.to_thread. Returns [{"id", "name", "webViewLink",
    "mimeType"}, ...] sorted by name. Escapes ' and \ for the Drive query.
    """
```

Implementacja: `service.files().list(q=f"name contains '{escaped}' and trashed = false",
fields="files(id, name, webViewLink, mimeType)", pageSize=page_size, orderBy="name",
supportsAllDrives=True, includeItemsFromAllDrives=True).execute()["files"]`.
Escapowanie: `name_contains.replace("\\", "\\\\").replace("'", "\\'")`.

### 4. `parsers.py` — parser daty dla komendy

```python
def parse_date_arg(raw: str, *, today: date) -> Optional[date]:
    """User-supplied date: 'RRRR-MM-DD', 'DD.MM.RRRR', 'dzisiaj', 'wczoraj'."""
```

Czysta funkcja (jak reszta modułu): trim + lower; `dzisiaj` → `today`, `wczoraj` →
`today - timedelta(days=1)`; następnie `%Y-%m-%d`, potem `%d.%m.%Y`; inaczej `None`.

### 5. Nowy cog `cogs/admin_lookup.py` — `/admin transkrypt`

```python
class AdminLookup(commands.Cog):
    admin = app_commands.Group(
        name="admin", description="Narzędzia administracyjne Momentum",
        guild_only=True, default_permissions=discord.Permissions(administrator=True),
    )

    @admin.command(name="transkrypt", description="Link do transkryptu spotkania z danej daty")
    @app_commands.describe(data="Data spotkania: RRRR-MM-DD, DD.MM.RRRR, dzisiaj, wczoraj")
    @app_commands.checks.has_permissions(administrator=True)
    async def transkrypt(self, interaction, data: str): ...
```

Logika podkomendy (wszystkie odpowiedzi **ephemeral**):

1. `parse_date_arg` (today = Warsaw-local date, `ZoneInfo("Europe/Warsaw")`);
   `None` → komunikat o formacie.
2. `gdrive.is_configured()` == False → „Google Drive nie jest skonfigurowany”.
3. `await interaction.response.defer(ephemeral=True)` (wywołanie sieciowe), potem
   `files = await asyncio.to_thread(gdrive.find_files, f"Lifehackerzy_{d.isoformat()}")`.
4. Grupowanie wyników po spotkaniu: dla każdego pliku zdejmij sufiks
   (`-transcript.md` / `.md` / `.txt` / `.mp3`) i sparsuj bazę
   `parsers.parse_recording_filename(base + ".wav")` → klucz `(started, slug, rec_id)`.
   Dla każdego spotkania (sortuj po godzinie) linia embedu:
   `**HH:MM** #<slug> — [📝 transkrypt](link) · [🎙️ audio](link)`;
   transkrypt = plik `-transcript.md`, w braku → legacy `.txt` (opisz jako „📝 transkrypt (txt)”);
   brak transkryptu → sam audio z dopiskiem „(brak transkryptu)”.
5. Brak wyników → „Brak nagrań z {data} na Drive.” Wyjątek z Drive → log + komunikat błędu.
6. Handler `transkrypt.error` dla `MissingPermissions` → ephemeral „Tylko dla administratora.”

Rejestracja: standardowe `async def setup(bot): await bot.add_cog(AdminLookup(bot))`
(grupa jako atrybut klasy Cog jest zbierana automatycznie przy add_cog).

### 6. `main.py` — rejestracja rozszerzenia

Do `EXTENSIONS` (linia ~127, na końcu listy):
`"cogs.admin_lookup",  # /admin transkrypt — link do transkryptu z danej daty (admin)`.

### 7. `scripts/backfill_drive_transcripts.py` — jednorazowy backfill

Skrypt CLI (uruchamiany na VPS: `venv/bin/python scripts/backfill_drive_transcripts.py [--dry-run]`):

1. `load_dotenv()`; abort jeśli `not gdrive.is_configured()`.
2. Dla każdego `transcripts/*.md` (posortowane): `rec_id = stem.rsplit("_", 1)[-1]`
   (jak w `transcripts.find_orphans`).
3. `gdrive.find_files(rec_id)`:
   - jeśli wśród wyników jest już `*-transcript.md` → **skip** (idempotencja);
   - znajdź `.mp3` → stem docelowy = nazwa mp3 bez `.mp3`; upload lokalnego pliku
     (zawartość jest już pełnym dokumentem markdown) jako `<stem>-transcript.md`,
     mime `text/markdown`;
   - brak `.mp3` na Drive → **skip z logiem** (audio nigdy nie wjechało — nie zgadniemy
     nazwy z sekundami).
4. `--dry-run` — tylko wypisz co by zrobił. Na końcu podsumowanie: uploaded/skipped/no-audio.
5. Drobny throttle (`time.sleep(0.2)` między uploadami) — kurtuazja wobec API.

### 8. Testy (`tests/`)

- `tests/test_parsers.py`: `parse_date_arg` — ISO, `DD.MM.RRRR`, `dzisiaj`, `wczoraj`
  (deterministyczne `today=date(...)`), spacje/wielkość liter, śmieci → `None`.
- `tests/test_transcripts.py`: `render_document` — frontmatter (data/kanal/uczestnicy/id),
  body z `**Mówca:**`, pusty tekst → `""`; oraz że `save_transcript` zapisuje dokładnie
  `render_document(...)` (tmpdir, monkeypatch `TRANSCRIPTS_DIR` jak w istniejących testach).

### 9. Dokumentacja + git

- `CLAUDE.md`: tabela cogów (nowy wiersz `admin_lookup`), sekcja *Commands reference*
  (`/admin transkrypt <data>` — admin), opis pipeline'u („transkrypt jako
  `-transcript.md` obok MP3” zamiast `.txt`), wpis w changelogu 2026-08.
- Skopiuj ten plan do `docs/superpowers/specs/2026-08-18-drive-transcript-md-admin-lookup.md`
  (konwencja repo).
- Commit + push na `main` (standing preference), trailer
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Weryfikacja

1. `venv/bin/python -m py_compile transcripts.py gdrive.py parsers.py cogs/voicerecord.py cogs/admin_lookup.py main.py scripts/backfill_drive_transcripts.py`
2. `python3 -m unittest discover tests` — wszystkie zielone.
3. Deploy wg CLAUDE.md (`sudo -u ludwikc git pull` na VPS → `systemctl restart momentum-bot`
   → `journalctl -u momentum-bot --since "1 minute ago"`: „cog initialized”, „Synced N commands”,
   bez tracebacków; liczba komend +1).
4. Backfill: najpierw `--dry-run`, przejrzyj wynik, potem na ostro; sprawdź na Drive parę
   plików `-transcript.md` obok MP3.
5. E2E na Discordzie: `/admin transkrypt data:wczoraj` (admin) → ephemeral embed z linkiem
   📝/🎙️; ta sama komenda z konta bez uprawnień → komenda niewidoczna/odmowa. Po najbliższym
   nagraniu sprawdź, że nowy plik na Drive to `…-transcript.md` z frontmatterem.


## Rekomendacja modelu do implementacji

**Sonnet 5, effort medium** (przy implementacji obu speców z 2026-08-18 w jednej sesji: high — patrz spec zakładek).
