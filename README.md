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

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Create a Discord Bot and Get a Token

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" tab and click "Add Bot"
4. Under the "TOKEN" section, click "Copy" to copy your bot token
   - **IMPORTANT**: Keep this token secret! It's like a password for your bot.

### Step 5: Configure the Bot Token

1. Open the `private.py` file
2. Replace the placeholder token with your actual Discord bot token:

```python
DISCORD_TOKEN = "YOUR_ACTUAL_DISCORD_BOT_TOKEN_HERE"  # Replace with your actual token
```

### Step 6: Run the Bot

```bash
python main.py
```

## Features

- Various commands for server management
- Daily reminders
- Role assignment
- And more!

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
