# Momentum Bot - Ubuntu Server Deployment Guide

Quick reference for deploying and running the Momentum Discord Bot on Ubuntu servers.

## Quick Start

### Interactive Setup (Recommended)
```bash
bash quickstart.sh
```

This launches an interactive menu with all common operations.

---

## Manual Deployment

### 1. Test Everything
```bash
bash test_bot.sh
```

**What it checks:**
- ✅ Python 3.8+ installation
- ✅ Virtual environment setup
- ✅ Python dependencies (discord.py, pymongo, pytz)
- ✅ Helper modules (linkdb.py, emoji.py, etc.)
- ✅ Discord token configuration
- ✅ MongoDB connection
- ✅ Cog files existence
- ✅ Configuration validation

### 2. Run the Bot

**Foreground mode** (with tests):
```bash
bash run_bot.sh --test
```

**Background/daemon mode**:
```bash
bash run_bot.sh --daemon
```

**Verbose logging**:
```bash
bash run_bot.sh --test --verbose
```

### 3. Stop the Bot
```bash
# If running in background
kill $(cat bot.pid)

# Or force kill all
pkill -f "python3 main.py"
```

---

## Systemd Service (Auto-start on Boot)

### Installation

1. **Install service:**
   ```bash
   bash quickstart.sh
   # Select option 7: Install as systemd service
   ```

   Or manually:
   ```bash
   # Edit USERNAME in service file
   sudo cp momentum-bot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable momentum-bot
   ```

2. **Start service:**
   ```bash
   sudo systemctl start momentum-bot
   ```

### Service Management

```bash
# Start
sudo systemctl start momentum-bot

# Stop
sudo systemctl stop momentum-bot

# Restart
sudo systemctl restart momentum-bot

# Status
sudo systemctl status momentum-bot

# Enable auto-start on boot
sudo systemctl enable momentum-bot

# Disable auto-start
sudo systemctl disable momentum-bot

# View logs
sudo journalctl -u momentum-bot -f

# View last 100 lines
sudo journalctl -u momentum-bot -n 100
```

---

## Log Management

### View Logs

**Live tail:**
```bash
tail -f bot.log
```

**Last 50 lines:**
```bash
tail -50 bot.log
```

**Search logs:**
```bash
grep "ERROR" bot.log
grep "discord" bot.log -i
```

**Error log:**
```bash
tail -f error.log
```

### Log Rotation

Logs automatically rotate when they exceed 10MB (built into run_bot.sh).

**Manual rotation:**
```bash
mv bot.log bot.log.$(date +%Y%m%d)
touch bot.log
```

**Clear logs:**
```bash
> bot.log  # Clear but keep file
rm bot.log  # Delete completely
```

---

## Screen Session (Alternative to systemd)

### Run in Screen

```bash
# Create new screen session
screen -S momentum-bot

# Inside screen: start bot
bash run_bot.sh

# Detach from screen: Ctrl+A, then D
```

### Manage Screen

```bash
# List sessions
screen -ls

# Reattach to session
screen -r momentum-bot

# Kill session
screen -X -S momentum-bot quit
```

---

## Tmux Session (Another Alternative)

### Run in Tmux

```bash
# Create new tmux session
tmux new -s momentum-bot

# Inside tmux: start bot
bash run_bot.sh

# Detach from tmux: Ctrl+B, then D
```

### Manage Tmux

```bash
# List sessions
tmux ls

# Attach to session
tmux attach -t momentum-bot

# Kill session
tmux kill-session -t momentum-bot
```

---

## Monitoring and Health Checks

### Check if Bot is Running

```bash
# Check PID file
cat bot.pid
ps -p $(cat bot.pid)

# Find process
pgrep -af "python3 main.py"

# Full process info
ps aux | grep "main.py"
```

### Resource Usage

```bash
# Memory and CPU usage
top -p $(cat bot.pid)

# Or with htop
htop -p $(cat bot.pid)

# Check disk space
df -h
du -sh Momentum/
```

### Network Connectivity

```bash
# Test MongoDB connection
python3 -c "from linkdb import get_db; get_db().admin.command('ping'); print('OK')"

# Test Discord API (requires bot running)
# Check bot.log for connection messages
grep "Logged in as" bot.log
```

---

## Troubleshooting

### Bot Won't Start

1. **Run tests:**
   ```bash
   bash test_bot.sh
   ```

2. **Check Python version:**
   ```bash
   python3 --version  # Should be 3.8+
   ```

3. **Check dependencies:**
   ```bash
   source venv/bin/activate
   pip list | grep -E "discord|pymongo|pytz"
   ```

4. **Check token:**
   ```bash
   python3 -c "from private import DISCORD_TOKEN; print(len(DISCORD_TOKEN))"
   # Should be 70+ characters
   ```

5. **Check logs:**
   ```bash
   tail -50 bot.log
   tail -50 error.log
   ```

### Bot Keeps Crashing

1. **Check error log:**
   ```bash
   tail -100 error.log
   ```

2. **Check disk space:**
   ```bash
   df -h
   ```

3. **Check memory:**
   ```bash
   free -h
   ```

4. **Check MongoDB connection:**
   ```bash
   python3 -c "from linkdb import get_db; client = get_db(); print(client.list_database_names())"
   ```

5. **Run with verbose logging:**
   ```bash
   bash run_bot.sh --test --verbose
   ```

### Permission Issues

```bash
# Fix file permissions
chmod +x *.sh
chmod 644 *.py
chmod 644 config.py

# Fix ownership (replace USER)
sudo chown -R USER:USER ~/Momentum
```

### MongoDB Connection Fails

1. **Check URI:**
   ```bash
   grep MONGO_URI .env
   # Or
   python3 -c "from linkdb import MONGO_URI; print(MONGO_URI)"
   ```

2. **Test connection:**
   ```bash
   python3 linkdb.py
   ```

3. **Check MongoDB service (if local):**
   ```bash
   sudo systemctl status mongod
   ```

4. **Check firewall:**
   ```bash
   sudo ufw status
   # Allow MongoDB port if needed
   sudo ufw allow 27017
   ```

---

## Updates and Maintenance

### Update Bot Code

```bash
# Pull latest changes
git pull origin main

# Stop bot
sudo systemctl stop momentum-bot
# Or: kill $(cat bot.pid)

# Update dependencies
source venv/bin/activate
pip install -r requirements.txt --upgrade

# Restart bot
sudo systemctl start momentum-bot
# Or: bash run_bot.sh --daemon
```

### Backup Data

```bash
# Backup MongoDB (if local)
mongodump --out backup/$(date +%Y%m%d)

# Backup bot files
tar -czf momentum-backup-$(date +%Y%m%d).tar.gz \
    --exclude='venv' \
    --exclude='*.log' \
    --exclude='__pycache__' \
    Momentum/
```

### Clean Up

```bash
# Remove old logs
find . -name "*.log.old" -mtime +30 -delete

# Clear cache
rm -rf __pycache__ cogs/__pycache__

# Clean pip cache
pip cache purge
```

---

## Security Best Practices

### File Permissions

```bash
# Secure private files
chmod 600 private.py
chmod 600 .env

# Scripts should be executable
chmod 755 *.sh
```

### Firewall

```bash
# Check UFW status
sudo ufw status

# If MongoDB is on same server
sudo ufw allow from 127.0.0.1 to any port 27017

# Block external MongoDB access
sudo ufw deny 27017
```

### Keep Updated

```bash
# Update system packages
sudo apt update && sudo apt upgrade

# Update Python packages
pip list --outdated
pip install --upgrade discord.py pymongo pytz
```

---

## Quick Reference Commands

| Task | Command |
|------|---------|
| Test bot | `bash test_bot.sh` |
| Run bot (foreground) | `bash run_bot.sh --test` |
| Run bot (background) | `bash run_bot.sh --daemon` |
| Stop bot | `kill $(cat bot.pid)` |
| View logs | `tail -f bot.log` |
| Check status | `pgrep -af main.py` |
| Start service | `sudo systemctl start momentum-bot` |
| Stop service | `sudo systemctl stop momentum-bot` |
| Service status | `sudo systemctl status momentum-bot` |
| Service logs | `sudo journalctl -u momentum-bot -f` |

---

## Environment Variables

Add to `.env` file:

```bash
# Discord Bot Token
DISCORD_TOKEN=your_token_here

# MongoDB Connection
MONGO_URI=mongodb://localhost:27017/

# Optional: Debug mode
DEBUG=true
```

Load with:
```bash
source .env  # In bash
# Or bot loads automatically with python-dotenv
```

---

## Performance Tips

1. **Use virtual environment** - Isolated dependencies
2. **Use systemd** - Auto-restart on crashes
3. **Monitor logs** - Catch issues early
4. **Regular backups** - Protect your data
5. **Keep updated** - Security and bug fixes
6. **Use log rotation** - Prevent disk full
7. **Monitor resources** - Watch CPU/RAM usage

---

## Support

- **Documentation:** See [Claude.MD](Claude.MD)
- **Setup Issues:** Run `bash test_bot.sh`
- **Logs:** Check `bot.log` and `error.log`
- **Interactive Help:** Run `bash quickstart.sh`

---

**Last Updated:** 2025-12-23
**Version:** 1.0.0
