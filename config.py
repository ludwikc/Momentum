# config.py
# Channel IDs
DAILY_CALL_CHANNEL_ID = 1120658406160732160  # Channel for daily calls
PROGRESS_CHANNEL_ID = 1225131519404675124    # Channel for progress tracking
SEKRET_CHANNEL_ID = 1196136652737892463      # Channel for anonymous messages

# Activity types and emojis (the /done choices)
ACTIVITIES = {
    "trening": "💪",
    "medytacja": "🧘",
    "sukces": "💎",
    "dziennik": "📝"
}

# Lifetime counters shown at the bottom of the shared "Aktywność" embed, in
# display order: (emoji, label). Includes the session-tracker activities
# (Daily Coaching, Deep Work) which are not /done choices. Deep Work is shown
# as accumulated connection time rather than a count.
COUNTERS = {
    "trening":        ("💪", "Trening"),
    "medytacja":      ("🧘", "Medytacja"),
    "sukces":         ("💎", "Sukces"),
    "dziennik":       ("📝", "Dziennik"),
    "daily_coaching": ("🔢", "Daily Coaching"),
    "deep_work":      ("⚓️", "Deep Work"),
}

# Morning greeting time settings
MORNING_GREETING_START_HOUR = 4
MORNING_GREETING_END_HOUR = 6
MORNING_GREETING_END_MINUTE = 55
