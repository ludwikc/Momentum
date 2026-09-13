# Momentum mówi — odpowiedzi głosowe na żywo w kanale głosowym (Tier 1)

## Kontekst

Momentum od dawna *słyszy* spotkanie (nagrywa, transkrybuje, streszcza), ale nie
potrafi się w nim odezwać. Cel: podczas trwającego nagrania ktoś mówi
„**Momentum**, co o tym myślisz?" — bot odpowiada **głosem** w tym samym kanale.

Zakres to świadomie **Tier 1**: wywołanie słowem-kluczem, jedna odpowiedź, brak
niezapowiedzianych wtrąceń. Bot **nie decyduje sam**, kiedy się odezwać — decyduje
człowiek, wołając go po imieniu. Tier 2 (samodzielne wtrącanie własnych spostrzeżeń)
jest celowo poza zakresem: kod to ~+150 linii, ale dostrojenie „kiedy przerwać ludziom"
to tygodnie pracy na żywym Daily Coachingu i realne ryzyko zepsucia rytuału. Decyzja
o Tier 2 po wysłuchaniu Tier 1 na prawdziwym spotkaniu.

Ustalenia (domyślne — do zmiany jednym stałą w configu):

- **Trigger surowszy niż w tekście.** `summon.is_summon` łapie „momentum" w dowolnym
  miejscu zdania — na kanale tekstowym to działa, ale na żywo oznaczałoby, że bot
  odzywa się **na głos** za każdym razem, gdy ktoś wspomni o nim w rozmowie. Na głosie
  słowo-klucz musi paść **na początku wypowiedzi** (pierwsze 3 słowa) — konwencja
  „Hey Siri". Kolizja ze specem `2026-08-18-voice-bookmarks-design.md`, który też
  rezerwuje wypowiedziane „Momentum": tam reguła zostaje luźna, bo zakładka jest cicha
  i post-hoc. Oba mechanizmy współistnieją (jedno wypowiedzenie może zrobić i zakładkę,
  i pytanie).
- **Dostęp: na start tylko admin/owner** — ten sam wzorzec gatingu, co wizja
  w przywołaniach. `VOICE_LIVE_ALLOW_EVERYONE = False`. Gating działa **przed** STT,
  więc wypowiedzi pozostałych uczestników nie idą nawet do Whispera (koszt ≈ 0).
- **Feature żyje tylko w trakcie nagrania.** Żadnego własnego zarządzania połączeniem
  głosowym — korzysta z `vc`, które `voicerecord` już trzyma. Nie ma nagrania → nie ma
  funkcji.
- **Głos bota trafia do nagrania.** Wypowiedź Momentum jest domiksowywana do WAV-a,
  więc płynie dalej normalnym pipeline'em (Whisper → diaryzacja → podsumowanie →
  zakładki) bez żadnych przypadków szczególnych. Inaczej archiwum spotkania
  *kłamałoby*: bot mówi, a w transkrypcie go nie ma.

Fakty o kodzie (z eksploracji — kluczowe dla wykonawcy):

- `MixingWaveSink.write(user, data)` (`mixsink.py:134`) leci na **wątku routera**, nie
  na pętli asyncio. `data.pcm` to dokładnie jedna ramka 20 ms / 48 kHz / stereo / 16-bit
  (3840 B), `data.packet.timestamp` to RTP, `data.packet.ssrc` identyfikuje mówcę,
  `user` to `discord.Member`. Cała klasa jest chroniona `threading.Lock`.
- **VAD masz za darmo.** Discord wysyła pakiety tylko wtedy, gdy ktoś mówi, a
  `_track_speaker` (`mixsink.py:178`) już skleja ramki w tury i zamyka turę, gdy przerwa
  przekroczy `DIARIZATION_GAP_FRAMES` (`config.py:68`, 25 ramek = 0,5 s). Nie potrzeba
  `webrtcvad` ani żadnego akustycznego VAD-a — granica wypowiedzi jest już liczona.
  **Pułapka:** tura zamyka się dopiero, gdy przyjdzie NOWA ramka po przerwie. Gdy ktoś
  skończy mówić i zapadnie cisza, żadna ramka nie przyjdzie i tura nigdy się nie
  domknie — stąd odpytywanie z pętli (pkt 3), a nie callback z sinka.
- Odtwarzanie na żywym połączeniu już działa: `vc.play(discord.FFmpegPCMAudio(sound))`
  (`voicerecord.py:186`, dźwięk startu). `VoiceRecvClient` dziedziczy po `VoiceClient`,
  więc `listen()` i `play()` działają jednocześnie.
- **Bot nie słyszy samego siebie** (`voicerecord.py:180-181`) — voice_recv odbiera RTP od
  innych, nie zapętla własnego wyjścia. Żadnej kompensacji echa, żadnej pętli sprzężenia.
- Mózg: `_generate_reply(user_msg, today_str, coaching, force_engage, offer_coaching,
  image_urls)` (`cogs/przywolanie.py:751`) — blokujący, do `asyncio.to_thread`. Okno
  rozmowy buduje `summon.build_summon_prompt(window, bot_user_id, direct_mention)`
  (`summon.py:228`) z listy dictów `{"author_id","display_name","is_bot","content"}` —
  wystarczy podać okno zbudowane z wypowiedzi głosowych zamiast z wiadomości.
- STT: `transcribe.transcribe(path) -> str` (`transcribe.py:122`) już kompresuje do
  16 kHz mono opus przed wysyłką. `is_configured()` keyuje po `OPENAI_API_KEY`.
- `_build_transcript` (`voicerecord.py:639`) konsumuje sidecar diaryzacji — **nie trzeba
  go dotykać**, bo głos bota wchodzi warstwę niżej, do miksu.

## Zmiany

### 1. `config.py` — blok `VOICE_LIVE_*` (pod blokiem `DIARIZATION_*`)

```python
# --- Momentum mówi: odpowiedzi głosowe na żywo (cogs/voice_live.py) ---
# Działa wyłącznie w trakcie nagrania prowadzonego przez cogs/voicerecord.py.
VOICE_LIVE_ENABLED = True
# Słowo-klucz musi paść w pierwszych N słowach wypowiedzi (konwencja "Hey Siri").
# Luźniejsza reguła oznaczałaby, że bot odzywa się NA GŁOS przy każdej wzmiance
# o sobie w rozmowie — na tekście to nie przeszkadza, na głosie jest nie do zniesienia.
VOICE_LIVE_WAKE_WORDS = ("momentum",)
VOICE_LIVE_WAKE_WINDOW_WORDS = 3
# Kto może wywołać bota głosem. False → tylko administratorzy i owner (jak wizja
# w przywołaniach). Gating sprawdzany PRZED transkrypcją, więc cudze wypowiedzi
# nie kosztują ani grosza.
VOICE_LIVE_ALLOW_EVERYONE = False
VOICE_LIVE_DAILY_LIMIT = 20        # wywołań na osobę na dobę (0 = bez limitu)
# Wypowiedź krótsza niż to ignorujemy (kaszlnięcie, "mhm") — nie ma czego słuchać.
VOICE_LIVE_MIN_SECONDS = 0.8
# Twardy sufit pojedynczej wypowiedzi; dłuższa jest cięta i wysyłana do STT w całości.
VOICE_LIVE_MAX_SECONDS = 30
# Ile ostatnich wypowiedzi (wszystkich mówców) tworzy okno kontekstu dla modelu.
VOICE_LIVE_CONTEXT_UTTERANCES = 12
# Cały łańcuch STT → model → TTS. Po przekroczeniu odpowiedź jest PORZUCANA:
# odezwanie się 40 s po pytaniu trafia już w inny temat i brzmi jak awaria.
VOICE_LIVE_TIMEOUT_S = 25
# Odpowiedź dłuższa niż to jest ucinana na granicy zdania przed syntezą (TTS jest
# płatne od znaku, a i tak nikt nie słucha bota przez minutę).
VOICE_LIVE_MAX_REPLY_CHARS = 600
VOICE_LIVE_TTS_MODEL = "gpt-4o-mini-tts"
VOICE_LIVE_TTS_VOICE = "onyx"
VOICE_LIVE_TTS_SPEED = 1.0
```

### 2. `mixsink.py` — podsłuch na żywo + ścieżka audio bota

Obie rzeczy to **obserwator/wejście obok istniejącej logiki** — dokładnie ta sama
konwencja, co side-channel diaryzacji opisany w `__init__` (linie 105-110). Miks,
pozycjonowanie po RTP i zapis WAV zostają nietknięte.

**a) Bufory wypowiedzi.** W `__init__` dołóż `self._live: dict[int, dict] = {}`
(ssrc → `{"user_id", "name", "pcm": bytearray, "first_tick", "last_wall"}`) oraz
`self.live_enabled = False` (ustawiane z zewnątrz; przy `False` cała ścieżka to jeden
`if` i zero kosztu). W `write()`, wewnątrz istniejącego `with self._lock`, **po**
`_track_speaker`:

```python
if self.live_enabled:
    self._live_append(ssrc, user, pcm, tick, now)
```

`_live_append` dopisuje ramkę do bufora mówcy (tworząc go przy pierwszej ramce)
i odświeża `last_wall`. Bufor przekraczający `VOICE_LIVE_MAX_SECONDS` przestaje
rosnąć (dalsze ramki odrzucane) — sufit pamięci.

**b) `take_finished_utterances(now, gap_seconds)`** — odpytywana z pętli cogu, bierze
`self._lock`, zwraca i **usuwa** bufory, w których `now - last_wall >= gap_seconds`:

```python
[{"user_id": int|None, "name": str, "pcm": bytes,
  "start": float,   # sekundy od początku nagrania (first_tick * 0.02)
  "seconds": float}, ...]
```

Bufory krótsze niż `VOICE_LIVE_MIN_SECONDS` są odrzucane bez zwracania. `gap_seconds`
podawany przez wołającego (domyślnie `DIARIZATION_GAP_FRAMES * 0.02` = 0,5 s), żeby
granica wypowiedzi na żywo była tą samą granicą, co w diaryzacji.

**c) `write_bot_frame(pcm)`** — wejście dla audio, które bot sam odtwarza. Bierze
`self._lock`, wyznacza tick z **zegara ściennego** (audio bota powstaje lokalnie: nie ma
RTP, nie ma jittera) i sumuje do kubełka dokładnie tak samo jak ramka mówcy, a potem
woła `_track_speaker` z zarezerwowanym `ssrc = 0` i nazwą `"Momentum"`
(`user_id = MOMENTUM_BOT_ID`). Dzięki temu:

- Whisper transkrybuje wypowiedź bota razem z resztą spotkania,
- diaryzacja przypisuje ją do „Momentum" bez żadnego przypadku szczególnego,
- podsumowanie, `/admin transkrypt` i (gdy powstaną) zakładki działają bez zmian.

Zarezerwowany `ssrc = 0`: Discord nie przydziela zera, więc kolizja z prawdziwym
mówcą jest niemożliwa. `_track_speaker` już dostaje `user` przez `getattr` — podaj
lekki obiekt-atrapę albo rozszerz podpis o opcjonalne `name`/`user_id`.

**d) `last_human_frame`** — pole z `time.perf_counter()` ostatniej ramki od człowieka,
aktualizowane w `write()`. Czyta je barge-in (pkt 3).

### 3. Nowy cog `cogs/voice_live.py`

Nie posiada połączenia głosowego — pożycza je z `voicerecord`:

```python
rec = self.bot.get_cog("VoiceRecord")
vc, sink = rec.vc, rec.sink          # voicerecord przechowuje sink w self.sink
```

`voicerecord._start` (`cogs/voicerecord.py:176`) musi więc zapamiętać sink
(`self.sink = sink`) i wyczyścić go w `_teardown` — dwie linie, jedyna zmiana w tym
pliku. Dodatkowo, tuż po utworzeniu sinka:
`sink.live_enabled = VOICE_LIVE_ENABLED`.

**Pętla** `@tasks.loop(seconds=0.25)`:

1. Brak nagrania / `sink is None` / wyłączone → return.
2. `for utt in sink.take_finished_utterances(time.perf_counter(), _GAP)`:
   - dopisz do `self._window` (deque, `maxlen=VOICE_LIVE_CONTEXT_UTTERANCES`) **dopiero
     po transkrypcji** (patrz niżej) — okno ma zawierać tekst, nie PCM;
   - **gating przed STT**: jeśli mówca nie jest uprawniony (`VOICE_LIVE_ALLOW_EVERYONE`
     ⊕ `guild_permissions.administrator` ⊕ `MOMENTUM_OWNER_ID`) → porzuć wypowiedź
     i nie transkrybuj;
   - `asyncio.create_task(self._handle(utt))`, żeby pętla nigdy nie blokowała.

**`_handle(utt)`** — całość w `asyncio.wait_for(..., VOICE_LIVE_TIMEOUT_S)` i w
`try/except Exception: logger.exception(...)` (zadanie fire-and-forget: wyjątek bez
wrappera ginie bez śladu — ta sama lekcja, co `_finish_and_publish`,
`voicerecord.py:439`):

1. `path = voice_live.pcm_to_wav(utt["pcm"], tmpdir)` → `text = await
   asyncio.to_thread(transcribe.transcribe, path)` → usuń plik w `finally`.
2. Dopisz `{"author_id", "display_name", "is_bot": False, "content": text}` do okna.
3. `if not voice_live.has_wake_word(text): return` — cisza, bez wołania modelu.
4. Limit dobowy (`summon.DailyRateLimiter`, `summon.py:137`, ten sam wzorzec co
   przywołania; owner zwolniony). Przekroczony → log + cisza (nie ma jak grzecznie
   odmówić głosem, nie zabierając czasu spotkaniu).
5. `user_msg = build_summon_prompt(list(self._window), self.bot.user.id,
   direct_mention=True)` — `direct_mention=True`, bo padło słowo-klucz na początku
   wypowiedzi: to jednoznaczne wywołanie, `[CISZA]` nie ma tu sensu.
6. `reply = await asyncio.to_thread(przywolanie.generate_reply, user_msg, today, False, True)`.
   W `cogs/przywolanie.py`, pod definicją `_generate_reply` (linia 785), dodaj alias
   `generate_reply = _generate_reply` — ten sam zabieg, co `join_words` w specu zakładek.
7. `speech = voice_live.strip_for_speech(reply)`; pusto → cisza.
8. `mp3 = await asyncio.to_thread(tts.synthesize, speech)`; `await self._speak(mp3)`.
9. Dopisz własną odpowiedź do okna jako `{"is_bot": True, ...}`, żeby model widział, co
   już powiedział.

**`_speak(mp3)`**:

- `vc.is_playing()` → `vc.stop()` (nowa odpowiedź unieważnia starą).
- `source = TeeSource(discord.FFmpegPCMAudio(mp3), sink.write_bot_frame)` — cienki
  `discord.AudioSource`, którego `read()` pobiera ramkę z opakowanego źródła, przekazuje
  jej **kopię** do `write_bot_frame` (best-effort, w `try/except`: błąd zapisu do miksu
  nigdy nie może uciszyć bota) i zwraca ramkę dalej. ~25 linii, w `voice_live.py`.
- `vc.play(source, after=...)`, potem czekaj na koniec z **barge-inem**: pętla
  `while vc.is_playing()` co 0,1 s; jeśli `sink.last_human_frame` jest świeższe niż
  0,2 s → `vc.stop()` i wyjście. Człowiek, który zaczyna mówić, zawsze wygrywa z botem.
- `finally`: usuń plik mp3.

### 4. Nowy czysty moduł `voice_live.py` (stdlib-only, unit-testowalny)

```python
def has_wake_word(text, *, words=VOICE_LIVE_WAKE_WORDS,
                  window=VOICE_LIVE_WAKE_WINDOW_WORDS) -> bool:
    """True, gdy słowo-klucz pada w pierwszych `window` słowach wypowiedzi.

    Porównanie po normalizacji (lower + zdjęta interpunkcja — Whisper dokleja
    przecinki: "Momentum, co myślisz?"). Świadomie SUROWSZE niż summon.is_summon:
    tam trafienie w środku zdania jest nieszkodliwe, tu każde trafienie odzywa się
    na głos w trakcie cudzej rozmowy. Pure.
    """

def strip_for_speech(text, *, limit=VOICE_LIVE_MAX_REPLY_CHARS) -> str:
    """Odpowiedź modelu → tekst nadający się do syntezy.

    Usuwa to, czego nie da się wypowiedzieć: <@123>/<#123>/<:emoji:123> (TTS czyta
    je dosłownie jako "mniejszość małpa sto dwadzieścia trzy"), markdown (**, __, `,
    nagłówki, bullety), gołe URL-e → "link". Przycina do `limit` na granicy zdania
    (kropka/!/?), a gdy jej nie ma — na granicy słowa. Pure.
    """

def pcm_to_wav(pcm: bytes, path: str) -> str:
    """Zapisz surowe 48 kHz/stereo/16-bit PCM jako WAV (moduł `wave`). Zwraca path."""
```

Domyślne wartości z `config` na poziomie modułu (jak w `transcripts.py`); testy
nadpisują przez argumenty keyword-only.

### 5. Nowy moduł `tts.py`

Symetryczny do `transcribe.py` (ten sam kształt, ten sam klucz):

```python
def is_configured() -> bool:            # bool(os.getenv("OPENAI_API_KEY"))
def synthesize(text: str) -> str:       # blokujące → asyncio.to_thread
    """Tekst → plik mp3 w tempdirze (ścieżka zwracana; woła usuwa).

    client.audio.speech.create(model=VOICE_LIVE_TTS_MODEL, voice=VOICE_LIVE_TTS_VOICE,
                               input=text, speed=VOICE_LIVE_TTS_SPEED,
                               response_format="mp3")
    """
```

`transcribe.is_quota_error` (`transcribe.py:39`) działa na tekście błędu, więc używaj go
też tutaj — wyczerpane kredyty ubijają STT, model i TTS naraz (patrz Known issues
w CLAUDE.md).

### 6. `main.py` — rejestracja

`"cogs.voice_live"` w `EXTENSIONS` **po** `"cogs.voicerecord"` (czyta jego stan przez
`get_cog`, więc kolejność ładowania nie jest krytyczna, ale porządek w liście ma
odzwierciedlać zależność).

### 7. Testy — `tests/test_voice_live.py`

- `has_wake_word`: `"Momentum, co myślisz?"` → True; `"momentum"` → True;
  `"Tak, myślę że Momentum to dobry pomysł"` → **False** (poza oknem — to jest cały
  sens tej funkcji); `"No i Momentum powiedział"` → False; pusty tekst → False;
  `window=99` przywraca zachowanie luźne.
- `strip_for_speech`: `<@404038151565213696>` znika; `**pogrubienie**` → `pogrubienie`;
  `https://…` → `link`; przycięcie na granicy zdania (tekst 700 znaków z kropką w 580.
  → kończy się kropką, ≤600); brak kropki → cięcie na spacji; pusty → `""`.
- `pcm_to_wav`: nagłówek ma 48000/2/2, `nframes` = `len(pcm)//4`.
- `MixingWaveSink.take_finished_utterances`: dwa mówcy → dwa osobne bufory; bufor
  świeższy niż `gap` **nie** wraca; zwrócony bufor znika (drugie wywołanie = pusto);
  bufor krótszy niż `VOICE_LIVE_MIN_SECONDS` odrzucony; `live_enabled=False` → nic się
  nie buforuje.
- `MixingWaveSink.write_bot_frame`: ramka ląduje w miksie (długość WAV rośnie) i tworzy
  segment diaryzacji z nazwą `"Momentum"`.

Uruchomienie: `python3 -m unittest discover tests`.

### 8. Dokumentacja + git

- `CLAUDE.md`: nowy wiersz w tabeli cogów (32 — `voice_live`), blok `VOICE_LIVE_*`
  w tabeli configu, `tts.py` + `voice_live.py` w „Helper modules" i w drzewie projektu,
  sekcja o pipelinie nagrań (głos bota jest w miksie), changelog 2026-09. Przy okazji
  tabela cogów jest już nieaktualna: sink to `MixingWaveSink`, nie
  `SilenceGeneratorSink(WaveSink)` — popraw.
- Spec → ten plik. Commit + push na `main`.

## Weryfikacja

1. `python3 -m unittest discover tests` + `py_compile` zmienionych plików.
2. Deploy wg CLAUDE.md; `journalctl -u momentum-bot` bez tracebacków, w logu
   `voice_live cog initialized`.
3. E2E na kanale testowym (dwie osoby albo obniżony `AUTO_RECORD_MIN_MEMBERS`):
   - „Momentum, co sądzisz o tym pomyśle?" → bot odpowiada głosem w ciągu ~10 s;
   - wspomnij „…myślę, że momentum jest ważne" w środku zdania → **cisza**;
   - zacznij mówić, gdy bot mówi → natychmiast milknie (barge-in);
   - poproś kogoś bez uprawnień admina o wywołanie → cisza, w logu brak wywołania STT;
   - po `/stop_nagrywania`: w `transcripts/*.md` blok `**Momentum:** …` z wypowiedzią
     bota, a w podsumowaniu na kanale uwzględniony jego wkład.
4. Kontrola kosztu po pierwszym prawdziwym Daily Coachingu: `usage_stats.py` / panel
   OpenAI — STT tylko z wypowiedzi uprawnionych, więc rachunek ma być groszowy.

## Ryzyka

- **Latencja 4–10 s** (Whisper ~1-2 s + `MOMENTUM_MODEL` = gpt-5.2 z narzędziami, czyli
  gros budżetu + TTS ~1 s). Wystarczy na świadomie zadane pytanie, za mało na rozmowę.
  Gdyby uwierało: `MOMENTUM_REASONING_EFFORT="none"` na tej ścieżce albo osobny,
  szybszy model dla głosu — przed sięganiem po Realtime API (Tier 3, przepisanie
  architektury i koszt w dolarach dziennie zamiast w groszach).
- **Jeden klucz OpenAI bez auto-doładowania** trzyma teraz STT, model, TTS, digest
  i podsumowania. Wyczerpanie ubija wszystko naraz — zdarzyło się (4–12.09.2026).
- `vc.play()` równolegle z `vc.listen()` pod DAVE jest w tym repo sprawdzone tylko na
  3-sekundowym dźwięku startu (`voicerecord.py:186`). To pierwsze miejsce, które robi
  to systematycznie — weryfikuj punktem 3, nie testem jednostkowym.
- Polskie TTS OpenAI brzmi poprawnie, ale ze słyszalnym akcentem. Jeśli to zgrzyta na
  produkcji, `VOICE_LIVE_TTS_*` są jedynym miejscem do podmiany dostawcy.

---

## Rekomendacja modelu do implementacji

**Opus 5, effort high.** Wyjątek od zwyczaju „Sonnet do prescriptywnych speców": tutaj
trzy punkty są nowe, a nie skopiowane z istniejącego wzorca — współbieżność wątku
routera z pętlą asyncio w `mixsink.py`, `TeeSource` wpinany w żywy `vc.play()` oraz
pożyczanie stanu (`vc`/`sink`) z cudzego, delikatnego cogu nagrywającego. Błąd w
którymkolwiek objawia się dopiero na produkcji, w trakcie Daily Coachingu, i może
zepsuć **nagranie** — czyli rzecz najcenniejszą w tym projekcie. Punkty 4, 5 i 7
(czyste moduły + testy) są na tyle mechaniczne, że w osobnej sesji zrobi je Sonnet 5
medium; punkty 2 i 3 zostaw Opusowi.
