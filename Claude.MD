# Momentum Discord Bot - Developer Documentation

## Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Setup and Installation](#setup-and-installation)
- [Configuration](#configuration)
- [Features and Cogs](#features-and-cogs)
- [Database Schema](#database-schema)
- [Commands Reference](#commands-reference)
- [Development Guide](#development-guide)
- [Troubleshooting](#troubleshooting)
- [Known Issues](#known-issues)
- [Contributing](#contributing)

---

## Overview

**Momentum** is a Polish-language Discord bot designed for community engagement, habit tracking, meeting coordination, and productivity features. The bot helps community members build momentum through daily habits, manage speaking queues during meetings, and track personal growth activities.

### Key Features
- Morning wake-up tracking with streak building
- Activity streak tracking (training, meditation, journaling, success)
- Automated daily meeting reminders
- Voice channel speaking queue management
- Automatic role assignment based on invite links
- Anonymous secret submission
- Q&A system for common questions

### Technology Stack
- **Framework:** discord.py (py-cord variant)
- **Database:** MongoDB
- **Language:** Python 3.8+
- **Timezone:** Europe/Warsaw (Polish Time)
- **Primary Language:** Polish

---

## Architecture

### Bot Design Pattern
The bot follows a **Cog-based architecture** where each feature is implemented as a separate extension (Cog) that can be loaded/unloaded independently.

```
main.py (Bot Core)
    ├── Loads cogs from EXTENSIONS list
    ├── Configures logging and intents
    ├── Syncs slash commands
    └── Starts event loop

Cogs (Features)
    ├── test_cog.py         - Testing commands
    ├── gmlistener.py       - Morning greeting listener
    ├── gm.py               - Manual wake-up command
    ├── dailyreminder.py    - Scheduled meeting reminders
    ├── auto_assign_role.py - Auto role assignment
    ├── done.py             - Activity tracking (slash)
    ├── prefixdone.py       - Legacy command redirects
    ├── queue_cog.py        - Speaking queue management
    ├── leaderboard.py      - Activity rankings
    ├── qacog.py            - Q&A system
    └── sekret.py           - Anonymous submissions
```

### Database Architecture
```
MongoDB
├── wakeup_db
│   └── wake_ups (user wake-up tracking)
└── activity_db
    └── activities (user activity streaks)
```

### Event Flow
1. **Message Events** → gmlistener.py, qacog.py (on_message)
2. **Member Join** → auto_assign_role.py (on_member_join)
3. **Voice State** → queue_cog.py (on_voice_state_update)
4. **Scheduled Tasks** → dailyreminder.py, auto_assign_role.py (tasks.loop)
5. **Commands** → Respective cog command handlers

---

## Project Structure

```
/home/user/Momentum/
├── main.py                    # Bot entry point (129 lines)
├── config.py                  # Configuration constants (18 lines)
├── README.md                  # User-facing documentation
├── .env                       # Environment variables (gitignored)
├── .gitignore                 # Git ignore rules
├── bot.log                    # Runtime logs (auto-generated)
├── error.txt                  # Error logs (auto-generated)
├── main.py.bak                # Main file backup
│
├── cogs/                      # Feature extensions
│   ├── test_cog.py           # Hello world test (14 lines)
│   ├── gmlistener.py         # Wake-up listener (132 lines)
│   ├── gm.py                 # Manual wake-up (125 lines)
│   ├── dailyreminder.py      # Meeting reminders (62 lines)
│   ├── auto_assign_role.py   # Role assignment (85 lines)
│   ├── done.py               # Activity tracking (89 lines)
│   ├── prefixdone.py         # Legacy redirects (32 lines)
│   ├── queue_cog.py          # Speaking queue (149 lines)
│   ├── leaderboard.py        # Rankings (98 lines)
│   ├── qacog.py              # Q&A system (54 lines)
│   ├── sekret.py             # Secrets (63 lines)
│   ├── queuecog.py           # DEPRECATED - has merge conflicts
│   └── 1234dailyreminder.py  # DEPRECATED - old version
│
└── venv/                      # Python virtual environment
```

### Total Project Statistics
- **Python Files:** 14 (excluding venv)
- **Total Lines of Code:** ~1,100+ (cogs only)
- **Git Commits:** 55+
- **Configured Channels:** 3
- **Activity Types:** 4
- **Commands:** 10+ (prefix + slash)
- **Database Collections:** 2
- **Background Tasks:** 2

---

## Setup and Installation

### Prerequisites
- Python 3.8 or higher
- MongoDB instance (local or MongoDB Atlas)
- Discord Bot Token (from Discord Developer Portal)

### Step-by-Step Setup

1. **Clone the Repository**
   ```bash
   git clone <repository-url>
   cd Momentum
   ```

2. **Create Virtual Environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Create Required Modules**

   The following modules are gitignored and must be created manually:

   **private.py** (Discord token):
   ```python
   DISCORD_TOKEN = "your_discord_bot_token_here"
   ```

   **linkdb.py** (MongoDB connection):
   ```python
   import pymongo

   def get_db():
       client = pymongo.MongoClient("mongodb://your_connection_string")
       return client
   ```

   **emoji.py** (Emoji definitions):
   ```python
   TRENING = "💪"
   MEDYTACJA = "🧘"
   SUKCES = "💎"
   DZIENNIK = "📝"
   # Add other emojis as needed
   ```

   **random_msg.py** (Random messages):
   ```python
   import random

   def get_random_wake_message():
       messages = [
           "Dzień dobry! Świetny start!",
           "GM! Budujemy momentum!",
           # Add more messages
       ]
       return random.choice(messages)
   ```

   **images.py** (Image URLs):
   ```python
   LEADERBOARD_THUMBNAIL = "https://example.com/image.png"
   # Add other image URLs
   ```

5. **Configure Environment**

   Create `.env` file:
   ```env
   DISCORD_TOKEN=your_discord_bot_token_here
   ```

6. **Set Up MongoDB**

   Create the following databases and collections:
   - `wakeup_db` → `wake_ups`
   - `activity_db` → `activities`

7. **Run the Bot**
   ```bash
   python main.py
   ```

### Verification
After starting, you should see:
```
INFO:momentum_bot.main:Logged in as YourBotName#1234
INFO:momentum_bot.main:Bot is ready!
INFO:momentum_bot.main:Slash commands synced successfully.
```

---

## Configuration

### config.py

All bot configuration is centralized in `config.py`:

```python
# Channel IDs (get from Discord - right-click channel → Copy ID)
DAILY_CALL_CHANNEL_ID = 1120658406160732160  # Meeting announcements
PROGRESS_CHANNEL_ID = 1225131519404675124    # Activity updates
SEKRET_CHANNEL_ID = 1196136652737892463      # Anonymous secrets

# Activity Types and Emojis
ACTIVITIES = {
    "trening": "💪",      # Training/workout
    "medytacja": "🧘",    # Meditation
    "sukces": "💎",       # Success/achievement
    "dziennik": "📝"      # Journal/diary
}

# Morning Greeting Time Window (Europe/Warsaw timezone)
MORNING_GREETING_START_HOUR = 4  # 4:00 AM
MORNING_GREETING_END_HOUR = 6    # 6:00 AM
```

### Invite-to-Role Mapping

Configured in `auto_assign_role.py`:

```python
INVITE_ROLE_MAPPING = {
    "4kXt95T53R": "1230797917913223279",  # Invite code → Role ID
    "vbvBptbUSk": "1224735643423215776",
    "Gy9MGxyv68": "1232624150418292746"
}
```

To add new mappings:
1. Create Discord invite link with custom code
2. Get role ID (right-click role → Copy ID)
3. Add to `INVITE_ROLE_MAPPING` dictionary

### Daily Reminder Schedule

Configured in `dailyreminder.py`:

```python
REMINDERS = [
    (12, 34, "🎯 Zaczynamy daily! Spotkanie o 12:34."),
    (12, 45, "⏰ ~14 minut pozostało!"),
    (12, 54, "⚠️ ~5 minut pozostało!"),
    (12, 59, "✅ Koniec daily! Dzięki za udział!")
]
```

### Discord Intents

Required intents configured in `main.py`:

```python
intents = discord.Intents.default()
intents.message_content = True  # Read message content
intents.members = True          # Track member joins
intents.voice_states = True     # Monitor voice channels
intents.guilds = True           # Server information
```

---

## Features and Cogs

### 1. test_cog.py - Testing Commands

**Purpose:** Simple test command for bot functionality verification

**Status:** ✅ Active

**Commands:**
- `!hello` - Responds with "Hello, world!"

**Usage:**
```
User: !hello
Bot: Hello, world!
```

---

### 2. gmlistener.py - Morning Greeting Listener

**Purpose:** Passive listener that tracks early wake-ups and builds momentum streaks

**Status:** ⚠️ Disabled (missing modules)

**Dependencies:** linkdb, emoji, random_msg

**Trigger Phrases:**
- "gm" (case-insensitive)
- "dzień dobry" (case-insensitive)

**Logic:**
1. Listens for trigger phrases in any channel
2. Checks if message is between 4:00-6:00 AM Warsaw time
3. Validates user hasn't already logged wake-up today
4. Updates/creates user record in database
5. Increments momentum streak if within time window
6. Resets momentum if outside time window

**Database Operations:**
```python
# Create new user record
{
    "user_id": "123456789",
    "last_wakeup": datetime.now(),
    "streak_wakeups": 1,
    "streak_momentum": 1  # Only increments if 4-6 AM
}

# Update existing record
user["streak_wakeups"] += 1
if 4 <= hour < 6:
    user["streak_momentum"] += 1
else:
    user["streak_momentum"] = 0  # Reset momentum
```

**Response Messages:**
- Early wake-up (4-6 AM): Random motivational message
- Outside window: "Dzień dobry! Ale to nie jest wczesne wstawanie 😅"
- Duplicate: "Już się dziś obudziłeś/aś! 🌅"

---

### 3. gm.py - Manual Wake-Up Command

**Purpose:** Manual wake-up tracking command (alternative to gmlistener)

**Status:** ⚠️ Disabled (missing modules)

**Dependencies:** linkdb, emoji, random_msg

**Commands:**
- `!gm` (prefix)
- `/gm` (slash)

**Features:**
- Identical logic to gmlistener.py
- Manual trigger instead of passive listening
- Useful for users who prefer explicit commands

**Use Case:**
When gmlistener is disabled or for users who want to manually log wake-ups without typing "gm" in chat.

---

### 4. dailyreminder.py - Meeting Reminders

**Purpose:** Automated daily meeting notifications

**Status:** ✅ Active

**Type:** Background task (loops every 1 minute)

**Schedule (Warsaw Time):**
| Time  | Message                                      |
|-------|----------------------------------------------|
| 12:34 | 🎯 Zaczynamy daily! Spotkanie o 12:34.       |
| 12:45 | ⏰ ~14 minut pozostało!                      |
| 12:54 | ⚠️ ~5 minut pozostało!                       |
| 12:59 | ✅ Koniec daily! Dzięki za udział!          |

**Target Channel:** `DAILY_CALL_CHANNEL_ID`

**Implementation Details:**
```python
@tasks.loop(minutes=1)
async def send_daily_reminder():
    warsaw_tz = pytz.timezone('Europe/Warsaw')
    current_time = datetime.now(warsaw_tz)

    for hour, minute, message in REMINDERS:
        if current_time.hour == hour and current_time.minute == minute:
            channel = bot.get_channel(DAILY_CALL_CHANNEL_ID)
            await channel.send(message)
```

**Customization:**
Edit `REMINDERS` list in the cog to add/modify reminder times and messages.

---

### 5. auto_assign_role.py - Automatic Role Assignment

**Purpose:** Assigns roles to new members based on which invite link they used

**Status:** ✅ Active

**Events:**
- `on_member_join` - Triggers role assignment
- Background task (1-minute loop) - Updates invite cache

**How It Works:**
1. Caches all guild invites and their use counts
2. When member joins, compares current invites to cache
3. Finds invite with increased use count
4. Looks up role ID from `INVITE_ROLE_MAPPING`
5. Assigns role to new member

**Configuration:**
```python
INVITE_ROLE_MAPPING = {
    "invite_code": "role_id",
    # Example:
    "4kXt95T53R": "1230797917913223279"
}
```

**Logging:**
```
INFO: Member {user} joined using invite {code}
INFO: Assigned role {role_id} to {user}
ERROR: Failed to assign role: {error}
```

**Edge Cases:**
- Multiple invites used simultaneously: Assigns first match found
- Invalid role ID: Logs error, no role assigned
- Invite not in mapping: No action taken
- Bot lacks permissions: Logs error

---

### 6. done.py - Activity Streak Tracking

**Purpose:** Track user activity streaks for personal development

**Status:** ⚠️ Disabled (merge conflict issues)

**Dependencies:** linkdb, config.ACTIVITIES

**Command:**
- `/done <activity>` (slash only)

**Supported Activities:**
- `trening` (💪) - Training/workout
- `medytacja` (🧘) - Meditation
- `sukces` (💎) - Success/achievement
- `dziennik` (📝) - Journal entry

**Features:**
- Increments daily streak for specified activity
- Monthly reset (resets all streaks on 1st of month)
- Displays all user streaks in embed
- Shows user avatar in response

**Usage:**
```
User: /done trening
Bot: [Embed]
     💪 Trening: 5 days
     🧘 Medytacja: 2 days
     💎 Sukces: 0 days
     📝 Dziennik: 3 days
```

**Database Schema:**
```python
{
    "user_id": "123456789",
    "streaks": {
        "trening": 5,
        "medytacja": 2,
        "sukces": 0,
        "dziennik": 3
    },
    "last_reset": "2025-12-01"  # YYYY-MM-DD format
}
```

**Monthly Reset Logic:**
```python
current_month = datetime.now().strftime("%Y-%m")
if user_data["last_reset"] != current_month:
    # Reset all streaks to 0
    user_data["streaks"] = {activity: 0 for activity in ACTIVITIES}
    user_data["last_reset"] = current_month
```

---

### 7. prefixdone.py - Legacy Command Redirects

**Purpose:** Redirect users from old prefix commands to new slash commands

**Status:** ✅ Active

**Commands:**
- `!trening` → "Use `/done trening` instead"
- `!medytacja` → "Use `/done medytacja` instead"
- `!sumit` → "Use `/done sukces` instead" (alias)
- `!dziennik` → "Use `/done dziennik` instead"
- `!done` → "Use `/done <activity>` instead"

**Response:**
```
User: !trening
Bot: Ta komenda została zastąpiona przez `/done trening`. Użyj slash command! 😊
```

**Purpose:**
Smooth migration from prefix commands to Discord's native slash commands.

---

### 8. queue_cog.py - Speaking Queue Management

**Purpose:** Manage speaking order during voice channel meetings

**Status:** ⚠️ Active (clean version, queuecog.py has merge conflicts)

**Commands:**
- `/kolejka` - Add yourself to speaking queue
- `/kolejka_next` - Move to next speaker (moderator)
- `/kolejka_done` - Mark your turn as finished

**Events:**
- `on_voice_state_update` - Monitors mute/unmute states

**Features:**
1. **Queue Management:**
   - Users add themselves with `/kolejka`
   - Queue displays with numbered positions
   - Current speaker shown at top

2. **Auto-Progression:**
   - Monitors current speaker's mute status
   - If muted for 5+ seconds, auto-advances queue
   - Announces next speaker

3. **Manual Controls:**
   - Moderators can force next with `/kolejka_next`
   - Users can mark turn complete with `/kolejka_done`

**Usage Example:**
```
User A: /kolejka
Bot: Kolejka mówienia:
     1️⃣ 🎤 User A (teraz mówi)

User B: /kolejka
Bot: Kolejka mówienia:
     1️⃣ 🎤 User A (teraz mówi)
     2️⃣ User B

[User A mutes for 5+ seconds]
Bot: User A zakończył. Teraz mówi: User B 🎤

Bot: Kolejka mówienia:
     1️⃣ 🎤 User B (teraz mówi)
```

**State Management:**
```python
queue = []              # List of user IDs in order
current_speaker = None  # Current speaker's user ID
muted_since = None      # Timestamp when speaker muted
```

**Target Channel:** `DAILY_CALL_CHANNEL_ID` for announcements

---

### 9. leaderboard.py - Activity Rankings

**Purpose:** Display top performers for each activity type

**Status:** ⚠️ Disabled (missing emoji and images modules)

**Dependencies:** linkdb, emoji, images

**Command:**
- `/leaderboard <activity>` (slash)

**Supported Activities:**
- `trening` (💪)
- `medytacja` (🧘)
- `sukces` (💎)
- `dziennik` (📝)

**Features:**
- Top 10 rankings per activity
- Fetches user info from Discord
- Displays streak counts
- Formatted embed with thumbnail

**Response Format:**
```
[Embed]
Title: 💪 Leaderboard - Trening
Description:
  1. @User1 - 45 days
  2. @User2 - 32 days
  3. @User3 - 28 days
  ...
Thumbnail: [Activity icon]
```

**Database Query:**
```python
# Get all users sorted by specific activity streak
users = collection.find().sort(f"streaks.{activity}", -1).limit(10)
```

---

### 10. qacog.py - Q&A System

**Purpose:** Automated responses to frequently asked questions

**Status:** ⚠️ Disabled (merge conflict issues)

**Commands:**
- `/pytanie <question>` (manual lookup)

**Events:**
- `on_message` - Auto-responds to messages ending with "?"

**Predefined Q&A Pairs:**

| Question                      | Answer                                           |
|-------------------------------|--------------------------------------------------|
| co to jest momentum           | Momentum to nasza społeczność...                 |
| jak działa bot                | Bot śledzi aktywności, przypomina o spotkaniach  |
| kiedy spotkanie               | Spotkania odbywają się codziennie o 12:34        |
| jak dołączyć do kolejki       | Użyj komendy `/kolejka` w czasie spotkania       |
| jak zgłosić sekret            | Użyj komendy `/sekret` z wiadomością             |

**Features:**
- Exact match search (case-insensitive)
- Partial match fallback
- Auto-response to questions (messages with "?")
- Manual lookup with `/pytanie`

**Usage:**
```
User: Kiedy spotkanie?
Bot: Spotkania odbywają się codziennie o 12:34

User: /pytanie co to jest momentum
Bot: Momentum to nasza społeczność...
```

---

### 11. sekret.py - Anonymous Secrets

**Purpose:** Allow users to submit anonymous messages to dedicated channel

**Status:** ⚠️ Disabled (commented out in main.py)

**Command:**
- `/sekret <message>` (slash, ephemeral)

**Features:**
- Anonymous posting (bot posts on behalf of user)
- Spoiler tags for privacy (||message||)
- Message length validation (max 1900 chars)
- Channel-specific validation
- Ephemeral confirmation (only user sees confirmation)

**Target Channel:** `SEKRET_CHANNEL_ID` (1196136652737892463)

**Usage:**
```
User: /sekret I'm worried about the project deadline
Bot (ephemeral): Sekret został wysłany! 🤫
Bot (in secrets channel): ||I'm worried about the project deadline||
```

**Validation:**
```python
# Check message length
if len(message) > 1900:
    return "Wiadomość jest za długa! (max 1900 znaków)"

# Verify channel exists
channel = bot.get_channel(SEKRET_CHANNEL_ID)
if not channel:
    return "Nie mogę znaleźć kanału sekretów!"
```

**Privacy:**
- User's identity not revealed in posted message
- Ephemeral responses visible only to command user
- Spoiler tags require click to reveal content

---

## Database Schema

### MongoDB Collections

#### wakeup_db.wake_ups

**Purpose:** Track user wake-up times and momentum streaks

**Schema:**
```python
{
    "_id": ObjectId("..."),
    "user_id": "123456789012345678",  # Discord user ID (string)
    "last_wakeup": ISODate("2025-12-21T04:30:00Z"),  # UTC datetime
    "streak_wakeups": 15,  # Total consecutive wake-ups
    "streak_momentum": 10  # Consecutive early wake-ups (4-6 AM)
}
```

**Indexes:**
```javascript
db.wake_ups.createIndex({ "user_id": 1 }, { unique: true })
```

**Used By:** gmlistener.py, gm.py

**Operations:**
- **Create:** First wake-up for new user
- **Update:** Daily wake-up logs
- **Read:** Check last wake-up date, display streaks

**Streak Logic:**
- `streak_wakeups`: Increments on any wake-up log
- `streak_momentum`: Increments only for 4-6 AM wake-ups, resets outside window

---

#### activity_db.activities

**Purpose:** Track user activity streaks for personal development

**Schema:**
```python
{
    "_id": ObjectId("..."),
    "user_id": "123456789012345678",  # Discord user ID (string)
    "streaks": {
        "trening": 5,      # Training streak (days)
        "medytacja": 2,    # Meditation streak (days)
        "sukces": 0,       # Success streak (days)
        "dziennik": 3      # Journal streak (days)
    },
    "last_reset": "2025-12"  # YYYY-MM format for monthly reset
}
```

**Indexes:**
```javascript
db.activities.createIndex({ "user_id": 1 }, { unique: true })
db.activities.createIndex({ "streaks.trening": -1 })
db.activities.createIndex({ "streaks.medytacja": -1 })
db.activities.createIndex({ "streaks.sukces": -1 })
db.activities.createIndex({ "streaks.dziennik": -1 })
```

**Used By:** done.py, leaderboard.py

**Operations:**
- **Create:** First activity log for new user
- **Update:** Daily activity increments
- **Read:** Display user streaks, leaderboard rankings
- **Reset:** Monthly reset on 1st of each month

**Monthly Reset Logic:**
```python
current_month = datetime.now().strftime("%Y-%m")
if user_data["last_reset"] != current_month:
    user_data["streaks"] = {activity: 0 for activity in ACTIVITIES}
    user_data["last_reset"] = current_month
```

---

## Commands Reference

### Quick Command List

| Command | Type | Status | Description |
|---------|------|--------|-------------|
| `!hello` | Prefix | ✅ Active | Test command - responds with "Hello, world!" |
| `!gm` | Prefix | ⚠️ Disabled | Manual wake-up tracking (legacy) |
| `/gm` | Slash | ⚠️ Disabled | Manual wake-up tracking |
| `/done <activity>` | Slash | ⚠️ Disabled | Log daily activity (trening/medytacja/sukces/dziennik) |
| `!trening` | Prefix | ✅ Active | Redirect to `/done trening` |
| `!medytacja` | Prefix | ✅ Active | Redirect to `/done medytacja` |
| `!sumit` | Prefix | ✅ Active | Redirect to `/done sukces` |
| `!dziennik` | Prefix | ✅ Active | Redirect to `/done dziennik` |
| `!done` | Prefix | ✅ Active | Redirect to `/done` slash command |
| `/kolejka` | Slash | ⚠️ Disabled | Add yourself to speaking queue |
| `/kolejka_next` | Slash | ⚠️ Disabled | Move to next speaker (moderator) |
| `/kolejka_done` | Slash | ⚠️ Disabled | Mark your turn as finished |
| `/leaderboard <activity>` | Slash | ⚠️ Disabled | Show top 10 rankings for activity |
| `/pytanie <question>` | Slash | ⚠️ Disabled | Ask a predefined question |
| `/sekret <message>` | Slash | ⚠️ Disabled | Submit anonymous secret |

### Event Listeners

| Event | Cog | Status | Description |
|-------|-----|--------|-------------|
| `on_message` | gmlistener | ⚠️ Disabled | Detect "gm"/"dzień dobry" phrases |
| `on_message` | qacog | ⚠️ Disabled | Auto-respond to questions (messages with "?") |
| `on_member_join` | auto_assign_role | ✅ Active | Assign role based on invite used |
| `on_voice_state_update` | queue_cog | ⚠️ Disabled | Monitor speaker mute/unmute |

### Background Tasks

| Task | Interval | Cog | Status | Description |
|------|----------|-----|--------|-------------|
| Daily Reminders | 1 minute | dailyreminder | ✅ Active | Check time and send meeting reminders |
| Invite Cache | 1 minute | auto_assign_role | ✅ Active | Update invite usage cache |

---

## Development Guide

### Adding a New Cog

1. **Create Cog File**
   ```python
   # cogs/my_feature.py
   import discord
   from discord.ext import commands

   class MyFeature(commands.Cog):
       def __init__(self, bot):
           self.bot = bot

       @commands.slash_command(name="mycommand", description="My command")
       async def my_command(self, ctx):
           await ctx.respond("Hello from my feature!")

   def setup(bot):
       bot.add_cog(MyFeature(bot))
   ```

2. **Add to EXTENSIONS in main.py**
   ```python
   EXTENSIONS = [
       'cogs.test_cog',
       'cogs.my_feature',  # Add here
       # ... other cogs
   ]
   ```

3. **Test the Cog**
   ```bash
   python main.py
   # Bot will auto-load and sync slash commands
   ```

### Creating Database-Backed Features

1. **Import linkdb Module**
   ```python
   from linkdb import get_db
   ```

2. **Initialize Database Connection**
   ```python
   class MyCog(commands.Cog):
       def __init__(self, bot):
           self.bot = bot
           client = get_db()
           self.db = client["my_database"]
           self.collection = self.db["my_collection"]
   ```

3. **Perform Database Operations**
   ```python
   # Create/Update
   self.collection.update_one(
       {"user_id": str(ctx.author.id)},
       {"$set": {"data": "value"}},
       upsert=True
   )

   # Read
   user_data = self.collection.find_one({"user_id": str(ctx.author.id)})

   # Delete
   self.collection.delete_one({"user_id": str(ctx.author.id)})
   ```

### Implementing Background Tasks

```python
from discord.ext import tasks

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.my_task.start()  # Start task on cog load

    def cog_unload(self):
        self.my_task.cancel()  # Stop task on cog unload

    @tasks.loop(minutes=5)
    async def my_task(self):
        # Task logic here
        print("Task running every 5 minutes")

    @my_task.before_loop
    async def before_my_task(self):
        await self.bot.wait_until_ready()  # Wait for bot to be ready
```

### Logging Best Practices

```python
import logging

logger = logging.getLogger(f'momentum_bot.{__name__}')

# Usage in cog
logger.info("User %s used command %s", ctx.author, ctx.command)
logger.error("Failed to process: %s", error)
logger.debug("Debug info: %s", data)
```

**Log Levels:**
- **DEBUG:** Detailed information for diagnosing problems
- **INFO:** Confirmation that things are working as expected
- **WARNING:** Indication of unexpected events
- **ERROR:** Serious problems that prevent function execution
- **CRITICAL:** Very serious errors that may cause shutdown

### Code Style Guidelines

1. **Naming Conventions:**
   - Files: `snake_case.py`
   - Classes: `PascalCase`
   - Functions/variables: `snake_case`
   - Constants: `UPPER_CASE`

2. **Imports:**
   ```python
   # Standard library
   import logging
   import datetime

   # Third-party
   import discord
   from discord.ext import commands
   import pymongo

   # Local
   from config import ACTIVITIES
   import linkdb
   ```

3. **Command Naming:**
   - Use Polish names for user-facing commands
   - Use descriptive English names for internal functions
   - Keep command names lowercase
   - Use underscores for multi-word commands

4. **Error Handling:**
   ```python
   @commands.slash_command()
   async def my_command(self, ctx):
       try:
           # Command logic
           pass
       except Exception as e:
           logger.error(f"Error in my_command: {e}")
           await ctx.respond("Wystąpił błąd!", ephemeral=True)
   ```

### Testing Checklist

Before committing new features:
- [ ] Test slash command registration (appears in Discord)
- [ ] Test error handling (invalid inputs, missing permissions)
- [ ] Test database operations (create, read, update)
- [ ] Verify logging outputs (check bot.log)
- [ ] Test with multiple users simultaneously
- [ ] Check timezone handling (if applicable)
- [ ] Verify Polish character encoding (ą, ę, ć, etc.)
- [ ] Test edge cases (empty queue, duplicate entries, etc.)

---

## Troubleshooting

### Common Issues

#### "Improper token has been passed"
**Cause:** Invalid or missing Discord bot token

**Solutions:**
1. Verify token in `private.py` matches Discord Developer Portal
2. Ensure no extra spaces or quotes in token string
3. Regenerate token if compromised
4. Check `.env` file if using environment variables

```python
# private.py - Correct format
DISCORD_TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.GaBcDe.FgHiJkLmNoPqRsTuVwXyZ"
```

---

#### "No module named 'linkdb'"
**Cause:** Missing gitignored helper module

**Solution:**
Create `linkdb.py` with MongoDB connection:

```python
import pymongo
import os

def get_db():
    # Option 1: Environment variable
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

    # Option 2: Hardcoded (not recommended for production)
    # mongo_uri = "mongodb+srv://user:pass@cluster.mongodb.net/"

    client = pymongo.MongoClient(mongo_uri)
    return client
```

---

#### "No module named 'emoji'"
**Cause:** Missing gitignored emoji definitions

**Solution:**
Create `emoji.py` with emoji constants:

```python
# Activity emojis
TRENING = "💪"
MEDYTACJA = "🧘"
SUKCES = "💎"
DZIENNIK = "📝"

# Status emojis
FIRE = "🔥"
STAR = "⭐"
CHECKMARK = "✅"
WARNING = "⚠️"

# Add other emojis as needed
```

---

#### "No module named 'random_msg'"
**Cause:** Missing gitignored message templates

**Solution:**
Create `random_msg.py` with message functions:

```python
import random

def get_random_wake_message():
    messages = [
        "Dzień dobry! Świetny start dnia! 🌅",
        "GM! Budujemy momentum! 💪",
        "Wczesny start = produktywny dzień! ⭐",
        "Kolejny dzień, kolejny krok do celu! 🔥"
    ]
    return random.choice(messages)

def get_streak_message(streak):
    if streak >= 30:
        return f"Niesamowite! {streak} dni z rzędu! 🏆"
    elif streak >= 7:
        return f"Świetna passa! {streak} dni! 🔥"
    else:
        return f"Dobra robota! {streak} dni! ⭐"
```

---

#### "No module named 'images'"
**Cause:** Missing gitignored image URL definitions

**Solution:**
Create `images.py` with image URLs:

```python
# Leaderboard thumbnails
LEADERBOARD_THUMBNAIL = "https://example.com/leaderboard.png"

# Activity icons
TRENING_ICON = "https://example.com/trening.png"
MEDYTACJA_ICON = "https://example.com/medytacja.png"
SUKCES_ICON = "https://example.com/sukces.png"
DZIENNIK_ICON = "https://example.com/dziennik.png"

# Add other image URLs as needed
```

---

#### "Slash commands not appearing in Discord"
**Cause:** Commands not synced or bot lacks application.commands scope

**Solutions:**
1. Ensure bot has `application.commands` scope in OAuth2 URL
2. Wait 1-5 minutes for Discord to sync commands
3. Check bot logs for sync errors
4. Kick and re-invite bot with correct permissions

```python
# Verify sync in logs
INFO:momentum_bot.main:Slash commands synced successfully.
```

**OAuth2 URL Example:**
```
https://discord.com/api/oauth2/authorize?client_id=YOUR_BOT_ID&permissions=8&scope=bot%20applications.commands
```

---

#### "Background tasks not running"
**Cause:** Task not started or bot not ready

**Solutions:**
1. Verify `.start()` called in `__init__`
2. Add `@task.before_loop` with `wait_until_ready()`
3. Check for exceptions in task function

```python
@tasks.loop(minutes=1)
async def my_task(self):
    try:
        # Task logic
        pass
    except Exception as e:
        logger.error(f"Task error: {e}")

@my_task.before_loop
async def before_my_task(self):
    await self.bot.wait_until_ready()
```

---

#### "MongoDB connection timeout"
**Cause:** Invalid connection string or network issues

**Solutions:**
1. Verify MongoDB URI format
2. Check IP whitelist (MongoDB Atlas)
3. Test connection with MongoDB Compass
4. Ensure network allows outbound connections

```python
# Test connection
import pymongo
client = pymongo.MongoClient("your_uri_here", serverSelectionTimeoutMS=5000)
try:
    client.admin.command('ping')
    print("Connected successfully!")
except Exception as e:
    print(f"Connection failed: {e}")
```

---

#### "Voice state events not triggering"
**Cause:** Missing voice_states intent

**Solution:**
Ensure voice_states intent enabled:

```python
intents = discord.Intents.default()
intents.voice_states = True
bot = commands.Bot(intents=intents)
```

Also enable in Discord Developer Portal:
1. Go to Bot settings
2. Enable "Server Members Intent"
3. Enable "Message Content Intent"
4. Save changes

---

#### "Bot not responding to messages"
**Cause:** Missing message_content intent

**Solution:**
1. Enable in code:
   ```python
   intents.message_content = True
   ```

2. Enable in Discord Developer Portal:
   - Bot → Privileged Gateway Intents
   - Toggle "Message Content Intent"

3. Re-invite bot with updated permissions

---

### Debug Mode

Enable detailed logging:

```python
# main.py
logging.basicConfig(
    level=logging.DEBUG,  # Change from INFO to DEBUG
    format='%(asctime)s:%(levelname)s:%(name)s: %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
```

**View logs:**
```bash
tail -f bot.log  # Linux/Mac
Get-Content bot.log -Wait  # Windows PowerShell
```

---

## Known Issues

### Critical Issues

1. **Missing Helper Modules (Priority: High)**
   - **Files:** linkdb.py, emoji.py, random_msg.py, images.py, private.py
   - **Impact:** Most cogs are disabled due to missing imports
   - **Solution:** Create template versions of these files
   - **Status:** Documented in .gitignore, need manual creation

2. **Merge Conflicts (Priority: High)**
   - **File:** cogs/queuecog.py
   - **Issue:** Contains unresolved git merge markers (`<<<<<<<`, `=======`, `>>>>>>>`)
   - **Impact:** File cannot be loaded
   - **Solution:** Resolve conflicts or delete deprecated file
   - **Status:** Active version is queue_cog.py

3. **Command Type Inconsistency (Priority: Medium)**
   - **Issue:** Mix of prefix and slash commands
   - **Impact:** User confusion, inconsistent experience
   - **Recommendation:** Standardize on slash commands
   - **Status:** Migration in progress (prefixdone.py redirects users)

### Non-Critical Issues

4. **Duplicate Cogs (Priority: Low)**
   - **Files:** 1234dailyreminder.py (old), dailyreminder.py (current)
   - **Impact:** Code duplication, confusion
   - **Solution:** Delete deprecated version
   - **Status:** Old version not loaded in main.py

5. **Hardcoded Channel IDs (Priority: Low)**
   - **Issue:** Channel IDs in config.py are server-specific
   - **Impact:** Bot won't work in other servers without modification
   - **Recommendation:** Support multi-server configuration
   - **Status:** Acceptable for single-server bot

6. **No Permission Validation (Priority: Medium)**
   - **Issue:** Commands like `/kolejka_next` don't check user permissions
   - **Impact:** Any user can control queue
   - **Recommendation:** Add role/permission checks
   - **Status:** TODO

7. **No Rate Limiting (Priority: Low)**
   - **Issue:** No cooldowns on commands
   - **Impact:** Potential spam/abuse
   - **Recommendation:** Add command cooldowns
   - **Status:** TODO

8. **Missing Error Messages in Polish (Priority: Low)**
   - **Issue:** Some error messages in English
   - **Impact:** Inconsistent user experience
   - **Recommendation:** Translate all user-facing text
   - **Status:** Ongoing

---

## Contributing

### Development Workflow

1. **Fork and Clone**
   ```bash
   git clone <your-fork-url>
   cd Momentum
   git remote add upstream <original-repo-url>
   ```

2. **Create Feature Branch**
   ```bash
   git checkout -b feature/my-new-feature
   ```

3. **Make Changes**
   - Follow code style guidelines
   - Add logging statements
   - Update this documentation if needed
   - Test thoroughly

4. **Commit Changes**
   ```bash
   git add .
   git commit -m "Add: New feature description"
   ```

   **Commit Message Format:**
   - `Add:` New features
   - `Fix:` Bug fixes
   - `Update:` Improvements to existing features
   - `Refactor:` Code restructuring
   - `Docs:` Documentation changes
   - `Test:` Test additions/modifications

5. **Push and Create PR**
   ```bash
   git push origin feature/my-new-feature
   # Create pull request on GitHub
   ```

### Pull Request Guidelines

**PR Title Format:**
```
[Type] Brief description (max 60 chars)

Examples:
[Feature] Add role-based queue permissions
[Fix] Resolve timezone issue in wake-up tracking
[Docs] Update setup instructions
```

**PR Description Template:**
```markdown
## Summary
Brief description of changes

## Changes Made
- Change 1
- Change 2

## Testing
How were changes tested?

## Screenshots (if applicable)
[Add screenshots]

## Checklist
- [ ] Code follows style guidelines
- [ ] All tests pass
- [ ] Documentation updated
- [ ] No new warnings in logs
- [ ] Tested with multiple users
```

### Code Review Checklist

Reviewers should check:
- [ ] Code quality and style
- [ ] Error handling present
- [ ] Logging statements included
- [ ] Database queries optimized
- [ ] Polish language strings
- [ ] No hardcoded secrets/tokens
- [ ] Tests pass (if applicable)
- [ ] Documentation updated

---

## Future Enhancements

### Planned Features

1. **Multi-Server Support**
   - Per-server configuration
   - Database separation by guild_id
   - Dynamic channel/role configuration

2. **Web Dashboard**
   - View leaderboards online
   - User profile pages
   - Activity graphs and statistics
   - Admin panel for configuration

3. **Advanced Analytics**
   - Trend analysis for activities
   - Streak predictions
   - Community health metrics
   - Export data to CSV/JSON

4. **Gamification**
   - Badges and achievements
   - Level system
   - Monthly challenges
   - Rewards for streaks

5. **Integration Features**
   - Calendar integration for meetings
   - Webhook support for external tools
   - API for third-party apps
   - Export to Google Sheets

6. **Enhanced Queue System**
   - Time limits per speaker
   - Queue reservations
   - Priority queue levels
   - Voice activity detection

---

## License

MIT License - See LICENSE file for details

---

## Support and Contact

- **Issues:** Report bugs via GitHub Issues
- **Questions:** Ask in #momentum-help channel
- **Features:** Request via GitHub Discussions
- **Security:** Email security@momentum.com (replace with actual contact)

---

## Changelog

### Recent Updates

**2025-12-21**
- Created comprehensive Claude.MD documentation
- Documented all cogs and features
- Added troubleshooting guide
- Included database schemas

**Recent Commits:**
- Fix: Enable voice channel tracking and initialize bot with both prefix and slash commands
- Fix: Add logging for MongoDB connections and handle missing PyNaCl warnings
- Update bot initialization to use prefix commands only and skip syncing of slash commands
- BROKEN: Update logging and error handling in bot log
- Merge branch 'main' of https://github.com/ludwikc/Momentum

---

## Appendix

### Discord Bot Permissions

**Required Permissions:**
- Read Messages/View Channels
- Send Messages
- Send Messages in Threads
- Embed Links
- Attach Files
- Read Message History
- Add Reactions
- Use Slash Commands
- Manage Roles (for auto_assign_role)
- View Voice Channels (for queue_cog)
- Moderate Members (optional)

**Permission Integer:** `8` (Administrator) or calculate specific permissions

**OAuth2 Scopes:**
- `bot`
- `applications.commands`

### Useful Discord.py Resources

- **Documentation:** https://docs.pycord.dev/
- **GitHub:** https://github.com/Pycord-Development/pycord
- **Discord Server:** https://discord.gg/pycord
- **Examples:** https://github.com/Pycord-Development/pycord/tree/master/examples

### MongoDB Resources

- **Pymongo Docs:** https://pymongo.readthedocs.io/
- **MongoDB Atlas:** https://www.mongodb.com/cloud/atlas
- **Query Guide:** https://docs.mongodb.com/manual/tutorial/query-documents/

### Python Resources

- **Python 3.8+ Docs:** https://docs.python.org/3/
- **AsyncIO Guide:** https://docs.python.org/3/library/asyncio.html
- **Datetime Guide:** https://docs.python.org/3/library/datetime.html
- **Pytz Timezones:** https://pythonhosted.org/pytz/

---

**Last Updated:** 2025-12-21
**Version:** 1.0.0
**Author:** Momentum Development Team
**Repository:** ludwikc/Momentum
**Branch:** claude/discord-bot-documentation-xcqSa

---

*This documentation was generated by Claude Code for the Momentum Discord Bot project.*
