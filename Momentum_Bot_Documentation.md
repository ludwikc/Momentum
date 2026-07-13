# Momentum Discord Bot Documentation

This document provides a comprehensive overview of all features supported by the Momentum Discord bot, explaining the purpose and functionality of each component.

> **Bot identity:** Momentum is a standalone Discord application (ID `1468726880395067412`), distinct from **SIADLAXITY** (`1363266006516105456`), which is the separate siadlak.VIP portal bot. `main.py` verifies this identity at startup.

## Table of Contents

1. [Morning Greeting System](#morning-greeting-system)
2. [Activity Tracking](#activity-tracking)
3. [Daily Reminders](#daily-reminders)
4. [Role Management](#role-management)
5. [Anonymous Messaging](#anonymous-messaging)
6. [Leaderboards](#leaderboards)
7. [Queue Management](#queue-management)
8. [Q&A System](#qa-system)
9. [Basic Commands](#basic-commands)

---

## Morning Greeting System

### Purpose
The Morning Greeting System encourages users to maintain a consistent morning routine by tracking and rewarding early morning check-ins. It supports building a habit of waking up early through gamification.

### Functionality

#### Morning Check-ins
- **Passive Listener**: Automatically detects when users send messages containing "gm" or "dzień dobry" (Polish for "good morning")
- **Active Command**: Users can explicitly use the command to check in
- **Single Check-in Restriction**: Users can only check in once per day
- **Personalized Greetings**: Responses include personalized messages with the user's name and random motivational phrases. Exact message formats:
  - Early morning greeting: "🌅 **Dzień dobry @username!** [random motivational message] To twoja [count] pobudka z samego rana :raised_hands:! Twoje momentum wynosi [streak] 🔥!"
  - Regular greeting: "🌅 **Dzień dobry @username!** [random motivational message] :raised_hands:"
  - Repeat greeting error: "@username Za mało kawy? Tylko raz można się obudzić ☕️"

#### Momentum Tracking
- **Early Bird Recognition**: Special recognition for users who check in during designated early morning hours (4-6 AM by default)
- **Streak Counting**: Tracks consecutive days of early morning check-ins
- **Momentum Counter**: Maintains a separate "Momentum" count that increases with consistent early check-ins
- **Streak Reset**: Resets Momentum counter if the user checks in outside the early morning window

#### Data Storage
- Utilizes current Supabase to store:
  - User's last wake-up timestamp
  - Total wake-up count
  - Current Momentum streak

---

## Activity Tracking

### Purpose
The Activity Tracking system helps users maintain accountability for daily habits and routines by tracking specific activities and building streaks.

### Functionality

#### Activity Types
Four predefined activities with associated emojis:
- Training/Exercise (`trening`) 💪
- Meditation (`medytacja`) 🧘
- Success/Achievement (`sukces`) 💎
- Journaling (`dziennik`) 📝

#### Activity Commands
- **Slash Commands**: Modern interface using Discord's slash command system
  - Main command: `/done [activity]`
  - Activity selection via dropdown menu
- **Legacy Commands**: Support for older prefix commands (redirects to slash commands with informative messages)
  - `!trening` → "Hej @username, od teraz używamy **wyłącznie** nowocześniejszych komend `/done trening`, spróbuj raz jeszcze!"
  - `!medytacja` → "Hej @username, od teraz używamy **wyłącznie** nowocześniejszych komend `/done medytacja`, spróbuj raz jeszcze!"
  - `!sumit`, `!sukces`, `!mit` → "Hej @username, od teraz używamy **wyłącznie** nowocześniejszych komend `/done sukces`, spróbuj raz jeszcze!"
  - `!dziennik` → "Hej @username, od teraz używamy **wyłącznie** nowocześniejszych komend `/done dziennik`, spróbuj raz jeszcze!"
  - `!done` → "Hej @username, od teraz używamy **wyłącznie** slash komend `/done`. Proszę użyj polecenia zaczynającego się ukośnikiem `/` a nie wykrzyknikiem `!`"

#### Streak Management
- **Monthly Tracking**: Counts activities done within the current month
- **Monthly Reset**: Automatically resets all streaks at the beginning of each new month
- **Progress Visualization**: Shows an embed with all activity counts when a user logs an activity:
  - Title: "Aktywność" with purple color (#280586)
  - Main message: "🔥 To [count] [activity] w tym miesiącu!"
  - User's avatar displayed as thumbnail
  - List of all activities with their respective counts: "[emoji] [Activity name]: [count]"
  - Error message for invalid activities: "Niepoprawna aktywność. By zacząć streak wybierz z podanych aktywności: [activities list]"

#### Data Storage
- Utilizes MongoDB to store:
  - User activity counts for each activity type
  - Last reset date
  - User identification

---

## Daily Reminders

### Purpose
Facilitates structured daily coaching/meeting sessions by providing automated time-based reminders to keep participants on schedule.

### Functionality

#### Scheduled Reminders
- **Automated Messages**: Sends predefined messages to a designated channel at specific times
- **Fixed Schedule**: Operates on a preset daily schedule with exact messages:
  - 12:34 PM: "🕧 Witajcie na dzisiejszej sesji 12:34 Daily Coaching. <@272937604339466240> będzie nagrywać nasze spotkanie, aby potem je podsumować na Platformie. A więc bez zbędnych wstępów - zaczynajmy: co mogę dziś dla Was zrobić?"
  - 12:45 PM: "Tak tylko przypominam, że zostało nam ~14 minut spotkania."
  - 12:54 PM: "⏰ Kończymy za ~5 minut."
  - 12:59 PM: "🕐 12:59, pora wracać do stawiania czoła swoim wyzwaniom! Dziękuję za dziś i widzimy się jutro o 12:34!"
- **Consistent Timing**: Runs every day at the exact same times
- **Timezone Aware**: Operates in Polish timezone (Europe/Warsaw)

#### Technical Implementation
- Uses Discord.py's task scheduler to check time every minute
- References configuration for the specific channel ID to post reminders
- Includes logging for operational monitoring

---

## Role Management

### Purpose
Automatically assigns roles to new members based on which invite link they used to join the server, allowing for segmentation and streamlined onboarding based on user origin.

### Functionality

#### Invite Tracking
- **Invite Monitoring**: Monitors all server invites and their usage counts
- **Usage Detection**: Detects which invite link was used when a new member joins
- **Regular Updates**: Refreshes invite cache regularly to maintain accuracy

#### Role Assignment
- **Invite-Role Mapping**: Maintains a predefined mapping between invite codes and role IDs
- **Automatic Assignment**: When a new member joins, automatically assigns the appropriate role based on the invite they used
- **Logging**: Records role assignments for tracking and troubleshooting

#### Technical Implementation
- Keeps a cache of current invite usage counts
- Updates this cache regularly (every minute)
- Compares before/after counts when new members join to identify used invites
- Handles edge cases like members leaving (which affects invite counts)

---

## Anonymous Messaging

### Purpose
Provides a channel for community members to share thoughts, experiences, or questions anonymously, fostering open communication without social pressure.

### Functionality

#### Message Submission
- **Slash Command**: Users submit anonymous messages via `/sekret [message]`
- **Channel Restriction**: Command can only be used in a designated channel
- **Content Validation**: Checks message length (must be non-empty and under 1900 characters)

#### Message Handling
- **Anonymization**: Removes all user identification from the posted message
- **Formatting**: Formats messages with a standard template: "Lifehacker podzielił się właśnie sekretem: || [message] ||"
- **Spoiler Tags**: Wraps message content in Discord spoiler tags for sensitive content
- **Ephemeral Feedback**: Provides confirmation to the sender via ephemeral message (only visible to them)

#### Security & Privacy
- **True Anonymity**: No user identification is stored or associated with messages
- **Moderation Capability**: Posted in a designated channel that can be monitored by moderators

---

## Leaderboards

### Purpose
Fosters healthy competition and community engagement by showcasing the most active users for each activity type.

### Functionality

#### Leaderboard Generation
- **Slash Command**: Users can view leaderboards via `/leaderboard [activity]`
- **Activity Selection**: Supports all activity types (training, meditation, success, journaling)
- **Top Performers**: Displays top 10 users for the selected activity
- **Visual Presentation**: Uses Discord embeds with the following format:
  - Title: "🏆 Leaderboard dla [Activity name] [emoji]" with purple color (#280586)
  - Each user entry: "[rank]. [username]" with value "🔥 Total: [count]"
  - Empty leaderboard message: "Brak wyników" with value "Nikt jeszcze nie zaczął tej aktywności!"
  - Error message for invalid activities: "Niepoprawna aktywność. Dostępne aktywności: [activities list]"
  - Error message for generation issues: "Wystąpił błąd podczas generowania rankingu. Spróbuj ponownie później."

#### Leaderboard Data
- **Monthly Focus**: Shows data for the current month (matching the activity reset cycle)
- **User Identification**: Displays user display names for recognition
- **Count Display**: Shows the total number of activities completed
- **Visual Elements**: Includes thematic imagery and appropriate emojis

#### Technical Implementation
- Queries MongoDB for all users with activity data
- Sorts by activity count in descending order
- Limits results to top 10 entries
- Enriches data with user information from Discord API

---

## Queue Management

### Purpose
Manages user queues for events, support, or any situation requiring orderly participation, with voice channel integration.

### Functionality

**Note**: This feature appears to be partially implemented or disabled in the current codebase.

#### Core Features
- **Queue Creation**: System for creating and managing user queues
- **Member Management**: Adding/removing users from queues
- **Position Tracking**: Monitoring user positions in the queue
- **Voice Channel Integration**: Appears to interact with Discord voice channels

#### Technical Aspects
- Requires voice state tracking permissions
- Likely interacts with or monitors voice channel activity
- May include notification systems for queue position updates

---

## Q&A System

### Purpose
Facilitates structured question and answer interactions, possibly for community support, FAQs, or moderated Q&A sessions.

### Functionality

**Note**: This feature appears to be partially implemented or disabled in the current codebase.

#### Potential Features
- **Question Submission**: System for users to submit questions
- **Answer Management**: Interface for designated users to provide answers
- **Categorization**: Possible organization of Q&A by topic or category
- **Persistence**: Storage of questions and answers for future reference

---

## Basic Commands

### Purpose
Provides simple utility and testing commands to verify bot functionality or offer basic services.

### Functionality

#### Test Command
- **Hello Command**: Simple `!hello` response command for testing bot connectivity
- **Function**: Replies with "Hello, world!" when triggered

#### Technical Implementation
- Uses Discord.py's basic command structure
- Serves as both a functional test and example implementation
- Implemented as a standard cog for modularity

---

## Technical Implementation Overview

### Architecture
- **Modular Design**: Uses Discord.py's cog system for feature isolation
- **Database Integration**: MongoDB for persistent storage
- **Timezone Awareness**: Configured for Polish timezone (Europe/Warsaw)
- **Logging System**: Comprehensive logging for operations and error tracking

### Command Structure
- **Modern Slash Commands**: Primary interface using Discord's slash command system
- **Legacy Prefix Commands**: Maintains compatibility with older `!` prefix commands
- **Command Redirects**: Systems to guide users from old to new command formats

### Configuration
- **Channel IDs**: Designated channels for specific features
- **Activity Definitions**: Predefined activities with associated emojis
- **Time Windows**: Configured time periods for morning greetings
- **Invite Mappings**: Associations between invite codes and role IDs

### Data Management
- **User Tracking**: Systems to identify and track individual users
- **Streak Counting**: Algorithms for maintaining and resetting various streak counts
- **Monthly Cycles**: Monthly reset mechanisms for activity tracking
