# config.py
# Channel IDs
DAILY_CALL_CHANNEL_ID = 1120658406160732160  # Channel for daily calls
PROGRESS_CHANNEL_ID = 1225131519404675124    # Channel for progress tracking
SEKRET_CHANNEL_ID = 1196136652737892463      # Channel for anonymous messages

# Activity types and emojis
ACTIVITIES = {
    "trening": "💪", 
    "medytacja": "🧘", 
    "sukces": "💎", 
    "dziennik": "📝"
}

# Morning greeting time settings
MORNING_GREETING_START_HOUR = 4
MORNING_GREETING_END_HOUR = 6
MORNING_GREETING_END_MINUTE = 55

# Voice recording (cogs.voicerecord) settings
RECORDING_NOTIFY_CHANNEL_ID = 1015575570760880168  # channel where Drive links are posted
RECORDING_MAX_MINUTES = 120         # safety cap before a recording auto-stops

# Auto-record: start when a watched voice channel has >= AUTO_RECORD_MIN_MEMBERS
# non-bot members, stop when it drops below. Manual /nagraj works independently.
AUTO_RECORD_ENABLED = True
AUTO_RECORD_CHANNEL_IDS = [1120658406160732160]  # voice channels watched for auto-record
AUTO_RECORD_MIN_MEMBERS = 2

# Channels where the "now recording" intro (data/now_recording.*) is played on start.
START_SOUND_CHANNEL_IDS = [1120658406160732160]

# Daily invite announcement (cogs.daily_invite)
DAILY_INVITE_CHANNEL_ID = 1128649406640558110        # where the @here invite is posted
DAILY_INVITE_VOICE_CHANNEL_ID = 1120658406160732160  # voice channel linked in the message
DAILY_INVITE_TIME = "12:34"                           # Warsaw time (HH:MM)

# After recording one of these voice channels stops, post a thank-you listing
# everyone who participated to RECORDING_THANKYOU_CHANNEL_ID.
RECORDING_THANKYOU_VOICE_CHANNEL_IDS = [1120658406160732160]
RECORDING_THANKYOU_CHANNEL_ID = 1128649406640558110

# The thank-you greeting and the AI summary are only posted when at least this
# many distinct people took part in the recorded call (a 1-person call is skipped).
RECORDING_MIN_PARTICIPANTS = 2

# OpenAI transcription + summary (transcribe.py). Stays off unless OPENAI_API_KEY
# is set in the environment. After a recording stops, the audio is transcribed and
# an AI summary is posted to RECORDING_SUMMARY_CHANNEL_ID.
RECORDING_SUMMARY_CHANNEL_ID = 1128649406640558110  # where the AI summary is posted
OPENAI_TRANSCRIBE_MODEL = "whisper-1"  # must stay whisper-1: only it returns word timestamps
OPENAI_SUMMARY_MODEL = "gpt-4o-mini"

# Diarization (speaker-labeled transcripts). The MixingWaveSink already knows which
# Discord member every audio frame came from, so we record a speaking timeline next
# to the recording and attribute the Whisper transcript to speakers by timestamp —
# no acoustic ML needed. Off only if explicitly disabled; otherwise on whenever
# transcription is configured.
DIARIZATION_ENABLED = True
# Consecutive frames from the same speaker closer than this are treated as one turn,
# so natural micro-pauses don't fragment a turn into many tiny segments. In 20 ms
# frames: 25 = 0.5 s.
DIARIZATION_GAP_FRAMES = 25

# Momentum conversational summoning (cogs.przywolanie). Replies in-thread only
# when called by name ("Momentum") or @mention; uses the same OPENAI_API_KEY as
# transcribe.py.
MOMENTUM_MODEL = "gpt-5.2"        # OpenAI model used for in-conversation replies
MOMENTUM_CONTEXT_MESSAGES = 10    # how many recent messages to read as context
MOMENTUM_MAX_TOKENS = 250         # keep replies short (a few sentences)
MOMENTUM_TEMPERATURE = 0.8        # personality without chaos
# gpt-5.2 is a reasoning model: left unset it "thinks" at its default effort
# before every reply (seconds each), and that stacks across tool-call rounds.
# Lower = faster/shallower. One of "none","low","medium","high","xhigh"; ""
# omits the param entirely (for non-reasoning models). Auto-disabled at runtime
# if the model rejects it.
MOMENTUM_REASONING_EFFORT = "low"
# Transport for the summon model calls. False = Chat Completions (current).
# True = Responses API: chains tool rounds via previous_response_id so the model
# reuses prior reasoning/context instead of re-sending it — lower latency on
# multi-round coaching/advice replies. Rollout flag; flip on after a live check.
MOMENTUM_USE_RESPONSES = False

# Momentum can look up past meeting transcripts (saved by the recorder under
# transcripts/) via OpenAI tool-calls, so it can answer e.g. "co powiedział Jakub
# na wczorajszym spotkaniu". These bound that path.
MOMENTUM_TRANSCRIPT_MAX_TOKENS = 700   # answers grounded in a transcript may run longer
MOMENTUM_TRANSCRIPT_LIST_DAYS = 30     # default lookback when listing meetings
MOMENTUM_TRANSCRIPT_MAX_CHARS = 80000  # cap a single transcript fed back to the model
                                       # (~1h ≈ 29k chars; fits a full 120-min call)
MOMENTUM_TOOL_ROUNDS = 4               # max list/read tool round-trips per summon

# Safety / abuse limits (cogs.przywolanie):
# - Only the owner may DM the bot; everyone else's DMs are ignored outright.
# - Each non-owner may trigger at most MOMENTUM_DAILY_LIMIT summons per day
#   (Warsaw-local), checked before the OpenAI call so throttled users cost
#   zero tokens. The owner is exempt from both limits.
MOMENTUM_OWNER_ID = 404038151565213696
MOMENTUM_DAILY_LIMIT = 5

# This project's Discord application identity. SIADLAXITY (1363266006516105456)
# is a *separate* bot (the siadlak.VIP portal); if its token ever lands in
# private.py the bot would silently act as the wrong identity (wrong channels,
# "Missing Access"). main.py checks bot.user.id against this at startup and
# refuses to run on a mismatch.
MOMENTUM_BOT_ID = 1468726880395067412

# Baza wiedzy (cogs.przywolanie + scripts/ingest_knowledge.py). Momentum może
# przeszukać ~20k par temat→odpowiedź zapisanych w Supabase (tabela knowledge_base,
# wyszukiwanie hybrydowe pgvector+FTS przez RPC match_knowledge) — ale tylko gdy
# model uzna pytanie za istotne, więc zwykła rozmowa nie kosztuje tokenów bazy.
# EMBED_DIMS musi zgadzać się z wymiarem vector() w scripts/knowledge_schema.sql.
MOMENTUM_KB_ENABLED     = True
MOMENTUM_KB_EMBED_MODEL = "text-embedding-3-large"  # model embeddingów (import + zapytanie)
MOMENTUM_KB_EMBED_DIMS  = 1024                       # MUSI = vector(N) w schemacie
MOMENTUM_KB_MATCH_COUNT = 3                          # ile tematów zwracać (~2000 tok.)

# Coaching ma własny, MIESIĘCZNY limit per użytkownik (trwały — liczony w Supabase
# przez RPC log_capped_month na tabeli activity_logs, activity_type='coaching').
# Dotyczy obu wejść: /coaching-momentum oraz prośby w naturalnym języku. Właściciel
# jest zwolniony. Reset następuje na początku kolejnego miesiąca (czas warszawski).
MOMENTUM_COACHING_MONTHLY_LIMIT = 5

# =============================================================================
# StudyLion port (spec: docs/superpowers/specs/2026-07-11-studylion-port-design.md)
# Requires scripts/studylion_port.sql applied in Supabase.
# =============================================================================

# --- Monety (coin economy) ---
COINS_EMOJI = "🪙"
VOICE_COINS_PER_HOUR = 50          # StudyLion default: 50/h, pro-rated per second
VOICE_COIN_DAILY_CAP_HOURS = 16    # coins mint for at most this many voice hours/day
TASK_REWARD_COINS = 50             # per completed todo task (StudyLion default)
TASK_REWARD_LIMIT_24H = 10         # max rewarded tasks per rolling 24h (StudyLion default)
DONE_REWARD_COINS = 10             # bonus for /done activity log
GM_REWARD_COINS = 10               # bonus for the GM morning check-in

# --- Todo (/todo) ---
TODO_MAX_OPEN = 100                # max open (unticked) tasks per user
TODO_MAX_CONTENT = 100             # max task length (StudyLion default)

# --- Reminders (/przypomnij) ---
REMINDER_MAX_PER_USER = 25         # StudyLion default (Discord select cap)
REMINDER_MIN_REPEAT_SECONDS = 600  # min repeat interval (StudyLion default)
REMINDER_MAX_CONTENT = 2000

# --- Pomodoro (/pomodoro) ---
POMODORO_DEFAULT_FOCUS_MIN = 25
POMODORO_DEFAULT_BREAK_MIN = 5
POMODORO_MAX_STAGE_MIN = 1440      # StudyLion's per-stage bound

# --- Voice tracking ---
# All voice channels are tracked except these (e.g. an AFK channel).
UNTRACKED_VOICE_CHANNEL_IDS: list[int] = []
VOICE_FLUSH_MINUTES = 5            # periodic flush; bounds restart loss to <5 min

# --- Rangi (activity ranks) ---
# (hours, role_id, reward_coins) — lifetime tracked voice hours thresholds.
# Empty ⇒ the ranks cog stays dormant. StudyLion's template ladder for reference:
# [(1, <id>, 1000), (4, <id>, 2000), (8, <id>, 3000), (16, <id>, 4000),
#  (32, <id>, 5000), (64, <id>, 6000), (80, <id>, 7000)]
VOICE_RANKS: list[tuple[int, int, int]] = []
RANKS_ANNOUNCE_CHANNEL_ID = PROGRESS_CHANNEL_ID
