# Momentum Discord Bot

A Discord bot for the Momentum server.

## Setup Instructions

### Prerequisites

- Python 3.8 or higher
- A Discord account
- A Discord bot token

### Step 1: Clone the Repository

```bash
git clone https://github.com/yourusername/Momentum.git
cd Momentum
```

### Step 2: Set Up a Virtual Environment (Optional but Recommended)

```bash
python -m venv venv
# On Windows
venv\Scripts\activate
# On macOS/Linux
source venv/bin/activate
```

### Step 3: Set Up Helper Modules

The bot requires several helper modules that contain environment-specific configuration. These are gitignored for security reasons.

**Quick Setup:**
```bash
# Run the setup script to check and create required files
bash setup_helpers.sh
```

**Manual Setup:**

If the helper modules don't exist, you'll need to create them. The following files should already be present:
- `linkdb.py` - MongoDB connection configuration
- `emoji.py` - Emoji definitions
- `random_msg.py` - Message templates
- `images.py` - Image URL configuration

If any are missing, refer to the **Claude.MD** documentation for detailed setup instructions.

### Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 5: Configure MongoDB (Required)

Edit `linkdb.py` and set your MongoDB connection URI:

```python
# Option 1: Use environment variable (recommended)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

# Option 2: Hardcode (not recommended for production)
# MONGO_URI = "mongodb+srv://username:password@cluster.mongodb.net/"
```

Or add to `.env` file:
```
MONGO_URI=mongodb://localhost:27017/
```

### Step 6: Create a Discord Bot and Get a Token

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" tab and click "Add Bot"
4. Under the "TOKEN" section, click "Copy" to copy your bot token
   - **IMPORTANT**: Keep this token secret! It's like a password for your bot.

### Step 7: Configure the Bot Token

1. If `private.py` doesn't exist, copy from template:
   ```bash
   cp private.py.example private.py
   ```

2. Open the `private.py` file
3. Replace the placeholder token with your actual Discord bot token:

```python
DISCORD_TOKEN = "YOUR_ACTUAL_DISCORD_BOT_TOKEN_HERE"  # Replace with your actual token
```

### Step 8: Run the Bot

```bash
python main.py
```

If everything is configured correctly, you should see:
```
INFO:momentum_bot.main:Logged in as YourBotName#1234
INFO:momentum_bot.main:Bot is ready!
```

## Features

- **Morning Wake-Up Tracking** - Track early wake-ups (4-6 AM) and build momentum streaks
- **Activity Streaks** - Log daily activities: training, meditation, journaling, success
- **Automated Reminders** - Daily meeting notifications at scheduled times
- **Speaking Queue** - Manage speaking order during voice channel meetings
- **Auto Role Assignment** - Automatically assign roles based on invite links
- **Q&A System** - Automated responses to frequently asked questions
- **Anonymous Secrets** - Submit anonymous messages to dedicated channel
- **Leaderboards** - View top performers for each activity type

## Documentation

📖 **For comprehensive documentation, see [Claude.MD](Claude.MD)**

The Claude.MD file contains:
- Complete architecture overview
- Detailed cog documentation
- Database schemas
- Development guide
- Troubleshooting section
- API reference
- Contributing guidelines

## Troubleshooting

### "Improper token has been passed" Error

If you see this error, it means your Discord bot token is invalid or improperly formatted. Make sure:

1. You've replaced the placeholder in `private.py` with your actual token
2. The token is correctly copied from the Discord Developer Portal
3. The token is in the correct format (typically three sections separated by periods)

### Missing Module Errors

If you see errors about missing modules like `pytz`, make sure you've installed all dependencies:

```bash
pip install -r requirements.txt
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Commit your changes: `git commit -m 'Add some feature'`
4. Push to the branch: `git push origin feature-name`
5. Submit a pull request

## License

[MIT License](LICENSE)
