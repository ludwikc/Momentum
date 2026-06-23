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
OPENAI_TRANSCRIBE_MODEL = "whisper-1"
OPENAI_SUMMARY_MODEL = "gpt-4o-mini"

# Momentum conversational summoning (cogs.przywolanie). Replies in-thread only
# when called by name ("Momentum") or @mention; uses the same OPENAI_API_KEY as
# transcribe.py.
MOMENTUM_MODEL = "gpt-5.2"        # OpenAI model used for in-conversation replies
MOMENTUM_CONTEXT_MESSAGES = 10    # how many recent messages to read as context
MOMENTUM_MAX_TOKENS = 250         # keep replies short (a few sentences)
MOMENTUM_TEMPERATURE = 0.8        # personality without chaos
