# Coaching: krótkie strzały, autonomia rozmówcy, ciche wygaśnięcie oferty — spec

**Data:** 2026-07-31
**Źródło:** feedback Ani Warchoł z porannej rozmowy coachingowej na kanale Deep Work
(piątek, 08:35–08:58) + rekonstrukcja mechaniki z kodu.

## Problem

Zapis rozmowy pokazał trzy defekty zachowania Momentum w trybie coachingu:

1. **Ściany tekstu.** Każda odpowiedź coachingowa to wielopunktowy wykład
   (numerowane plany, timeboxy, teoria). Ania wprost: *„musisz konczyc
   konwersacje w miare szybko a nie ze spedza na pisaniu tutaj 20 min"*.
   Mechanika: tryb coachingu zawsze wywołuje `szukaj_w_bazie`, a użycie
   JAKIEGOKOLWIEK narzędzia podbija budżet odpowiedzi do
   `MOMENTUM_TRANSCRIPT_MAX_TOKENS` (1500) — cap pomyślany dla odpowiedzi
   z transkrypcji obejmuje też coaching. Prompt mówi tylko „zwięźle".

2. **Spieranie się z rozmówcą.** Ania trzykrotnie powiedziała, że pracuje
   „kreatywne najpierw, potem nudne" — bot trzykrotnie ją przekonywał do
   swojej kolejności („klasyczna ucieczka", „5 minut startu nudnego",
   renegocjacja jej planu). Prompt („masz zdanie i je stawiasz — bez
   owijania") nie ma przeciwwagi: żadnej reguły ustępowania, gdy rozmówca
   odrzuca radę i stawia własny sposób pracy.

3. **Niechciany follow-up po odejściu.** Ania napisała „znikam ide działac";
   jej wiadomość wywołała kolejny summon, model ponownie zaproponował tryb
   coachingowy (druga oferta w tej samej rozmowie, 8 minut po pierwszej),
   a po 120 s `CoachingOfferView.on_timeout` edytował ofertę na
   pasywno-agresywne *„Nie odpowiadasz, więc pewnie masz inne tematy na
   głowie…"* + pełny wykład — do osoby, której już nie było.

## Decyzje (zatwierdzone)

| # | Decyzja | Wybór |
|---|---|---|
| 1 | Długość odpowiedzi coachingowych | **Max 4 zdania + jeden ruch**; twardy limit w promptcie + koniec eskalacji capu tokenów dla coachingu |
| 2 | Reakcja na sprzeciw rozmówcy | **Challenge raz, potem wspieraj** jego plan; nigdy nie powtarzać odrzuconego argumentu |
| 3 | Timeout oferty coachingu | **Ciche wygaśnięcie** — bez „Nie odpowiadasz…", bez zrzucania przygotowanej odpowiedzi |
| 4 | Ponawianie oferty | **Cooldown 30 min** per (kanał, user), in-memory |

## Projekt

### 1. `SYSTEM_PROMPT` — nowa sekcja „AUTONOMIA ROZMÓWCY I KONIEC ROZMOWY"

Wstawiona po bloku „JAK SIĘ ODZYWASZ" (dotyczy każdej odpowiedzi, nie tylko
coachingu):

- Sposób pracy rozmówcy to JEGO decyzja; jedna kontrpropozycja max, potem
  przyjęcie jego planu i pomoc w domknięciu (ramy czasowe, pierwszy krok).
  Nigdy nie powtarzać odrzuconego argumentu.
- Sukces = szybki powrót rozmówcy do działania, nie długość rozmowy.
- Sygnał wyjścia („znikam", „idę działać", „nie mam czasu") → jedno krótkie
  zdanie pożegnania, zero nowych rad, zero pytań.

### 2. `COACHING_INSTRUCTION` — przepisanie

Zachowuje: jednoznaczne zaangażowanie (zakaz [CISZA]), oparcie o bazę wiedzy,
pewny ton. Dodaje: **MAKSYMALNIE 4 zdania i JEDEN konkretny ruch**, zakaz
numerowanych planów wielokrokowych (chyba że rozmówca wprost poprosi), jeden
wątek na raz, reguła autonomii (challenge raz), cel = powrót do działania.

### 3. Cap tokenów — tylko transkrypcje podbijają budżet

W obu pętlach (`_reply_via_chat`, `_reply_via_responses`) rozdzielić flagi:

- `tools_used` — bez zmian (gating wymuszenia KB w pierwszej rundzie),
- nowa `transcript_used` — ustawiana tylko przez `lista_spotkan` /
  `czytaj_spotkanie` (moduł. stała `_TRANSCRIPT_TOOLS`).

`cap = MOMENTUM_TRANSCRIPT_MAX_TOKENS if transcript_used else
MOMENTUM_MAX_TOKENS` — także w finalnym wywołaniu po wyczerpaniu rund.
`MOMENTUM_MAX_TOKENS` (1000) zostaje bez zmian: dzielony z reasoning
(gpt-5.2), więc obniżanie grozi pustymi odpowiedziami; widoczną długość
egzekwuje prompt, cap jest bezpiecznikiem.

### 4. `CoachingOfferView.on_timeout` — ciche wygaśnięcie

Edycja oferty na `„Oferta wygasła — zawołaj mnie, jak wrócisz 🙂"`, `view=None`.
Bez dumpa `regular_answer` (pole zostaje — używa go przycisk „Zwykła
odpowiedź"). Aktualizacja docstringa klasy.

### 5. Cooldown oferty — 30 min

- Nowa czysta funkcja `offer_allowed(last_offer_ts, now, cooldown_s)` w
  `summon.py` + testy w `summon_test.py` (zegar monotoniczny; `None` =
  nigdy nie oferowano).
- Cog: `self._offer_last: dict[tuple[int, int], float]` (channel_id,
  user_id) → `time.monotonic()`; zapis przy publikacji oferty; sprawdzenie
  w warunku `offer_eligible`.
- Nowy const `MOMENTUM_COACHING_OFFER_COOLDOWN_S = 1800` w `config.py`.
- Pas + szelki w promptcie: `COACHING_OFFER_INSTRUCTION` dostaje zdanie
  „nie flaguj [COACHING?], gdy w oknie rozmowy już trwa Twoja coachingowa
  wymiana z tą osobą albo niedawno jej to proponowałeś".

## Poza zakresem

- Powitania Deep Work (`greetings.py`, queue_cog) — nie były problemem.
- `MOMENTUM_MAX_TOKENS_RETRY`, transport Responses, limity dzienne/miesięczne.
- Trwałość cooldownu przez restart (in-memory wystarcza; wzorzec jak
  `DailyRateLimiter`).

## Weryfikacja

- `pytest summon_test.py greetings_test.py -q` — wszystkie zielone.
- `venv/bin/python -m py_compile cogs/przywolanie.py summon.py config.py`.
- Po deployu (git pull + restart na serwerze): ręczny test na kanale —
  summon z potencjałem coachingowym → oferta → klik 🧭 → odpowiedź ≤4 zdania;
  drugi summon w tej samej rozmowie → bez drugiej oferty; oferta zignorowana
  → po 120 s krótkie wygaśnięcie bez wykładu.
