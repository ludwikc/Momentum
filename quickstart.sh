#!/bin/bash
#
# Momentum Bot - Quick Start Script
# Interactive setup and launch for Ubuntu servers
#
# Usage: bash quickstart.sh
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

clear

echo -e "${CYAN}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║        MOMENTUM DISCORD BOT - Quick Start Guide          ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

echo "This script will help you set up and run the Momentum Discord Bot."
echo ""

# Main menu
show_menu() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}Main Menu${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "1. 🧪 Run system tests (check dependencies)"
    echo "2. 🚀 Start bot (foreground mode)"
    echo "3. 🔄 Start bot (background/daemon mode)"
    echo "4. 🛑 Stop bot (if running in background)"
    echo "5. 📊 Check bot status"
    echo "6. 📝 View logs (live tail)"
    echo "7. ⚙️  Install as systemd service"
    echo "8. 🔧 Setup helper modules"
    echo "9. 📦 Install/Update dependencies"
    echo "0. ❌ Exit"
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Function to wait for user
wait_for_user() {
    echo ""
    read -p "Press Enter to continue..." -r
    clear
}

# Option 1: Run tests
run_tests() {
    echo -e "${YELLOW}Running system tests...${NC}"
    echo ""
    bash test_bot.sh
    wait_for_user
}

# Option 2: Start bot (foreground)
start_bot_foreground() {
    echo -e "${GREEN}Starting bot in foreground mode...${NC}"
    echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
    echo ""
    sleep 2
    bash run_bot.sh --test
}

# Option 3: Start bot (background)
start_bot_daemon() {
    echo -e "${GREEN}Starting bot in background mode...${NC}"
    echo ""
    bash run_bot.sh --daemon

    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}✅ Bot is running in background${NC}"
        echo ""
        echo "Useful commands:"
        echo "  - View logs: tail -f bot.log"
        echo "  - Stop bot: Use option 4 in this menu"
    fi

    wait_for_user
}

# Option 4: Stop bot
stop_bot() {
    echo -e "${YELLOW}Stopping bot...${NC}"
    echo ""

    if [ -f "bot.pid" ]; then
        PID=$(cat bot.pid)
        if ps -p $PID > /dev/null 2>&1; then
            kill $PID
            sleep 2
            if ps -p $PID > /dev/null 2>&1; then
                echo -e "${RED}Failed to stop gracefully, forcing...${NC}"
                kill -9 $PID
            fi
            rm -f bot.pid
            echo -e "${GREEN}✅ Bot stopped${NC}"
        else
            echo -e "${YELLOW}Bot is not running (stale PID file)${NC}"
            rm -f bot.pid
        fi
    else
        echo -e "${YELLOW}No PID file found. Bot may not be running in background.${NC}"
        echo ""
        echo "Checking for running bot processes..."
        if pgrep -f "python3 main.py" > /dev/null; then
            echo -e "${YELLOW}Found running bot process(es):${NC}"
            pgrep -af "python3 main.py"
            echo ""
            read -p "Kill all bot processes? (y/N) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                pkill -f "python3 main.py"
                echo -e "${GREEN}✅ All bot processes killed${NC}"
            fi
        else
            echo -e "${GREEN}No bot processes found${NC}"
        fi
    fi

    wait_for_user
}

# Option 5: Check status
check_status() {
    echo -e "${CYAN}Bot Status Check${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    # Check PID file
    if [ -f "bot.pid" ]; then
        PID=$(cat bot.pid)
        if ps -p $PID > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Bot is running (PID: $PID)${NC}"

            # Get process info
            echo ""
            echo "Process info:"
            ps -p $PID -o pid,user,%cpu,%mem,etime,cmd

            # Check log file size
            if [ -f "bot.log" ]; then
                LOG_SIZE=$(stat -c%s bot.log 2>/dev/null || stat -f%z bot.log 2>/dev/null)
                LOG_SIZE_MB=$((LOG_SIZE / 1048576))
                echo ""
                echo "Log file size: ${LOG_SIZE_MB}MB"
            fi
        else
            echo -e "${RED}❌ Bot is not running (stale PID file)${NC}"
            rm -f bot.pid
        fi
    else
        echo -e "${YELLOW}No PID file found${NC}"

        # Check for running processes anyway
        if pgrep -f "python3 main.py" > /dev/null; then
            echo -e "${YELLOW}But found running bot process(es):${NC}"
            echo ""
            pgrep -af "python3 main.py"
        else
            echo -e "${RED}❌ Bot is not running${NC}"
        fi
    fi

    # Check systemd service (if installed)
    echo ""
    echo "Checking systemd service..."
    if systemctl list-unit-files | grep -q "momentum-bot.service"; then
        systemctl status momentum-bot.service --no-pager || true
    else
        echo "Systemd service not installed"
    fi

    wait_for_user
}

# Option 6: View logs
view_logs() {
    echo -e "${CYAN}Viewing bot logs (Ctrl+C to exit)${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    sleep 2

    if [ -f "bot.log" ]; then
        tail -f bot.log
    else
        echo -e "${RED}bot.log not found. Bot hasn't been run yet.${NC}"
        wait_for_user
    fi
}

# Option 7: Install systemd service
install_systemd() {
    echo -e "${CYAN}Installing as systemd service${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    # Check if running as root
    if [ "$EUID" -eq 0 ]; then
        echo -e "${RED}Don't run this script as root/sudo.${NC}"
        echo "The script will ask for sudo password when needed."
        wait_for_user
        return
    fi

    CURRENT_USER=$(whoami)
    CURRENT_DIR=$(pwd)

    echo "Creating systemd service file..."
    echo ""
    echo "Configuration:"
    echo "  User: $CURRENT_USER"
    echo "  Directory: $CURRENT_DIR"
    echo ""

    # Create temp service file with correct paths
    cat > /tmp/momentum-bot.service << EOF
[Unit]
Description=Momentum Discord Bot
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
Environment="PATH=$CURRENT_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$CURRENT_DIR/venv/bin/python3 $CURRENT_DIR/main.py

Restart=on-failure
RestartSec=10
StartLimitInterval=200
StartLimitBurst=5

StandardOutput=append:$CURRENT_DIR/bot.log
StandardError=append:$CURRENT_DIR/error.log

NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    echo "Installing service file (requires sudo)..."
    sudo cp /tmp/momentum-bot.service /etc/systemd/system/
    sudo systemctl daemon-reload

    echo ""
    read -p "Enable service to start on boot? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo systemctl enable momentum-bot
        echo -e "${GREEN}✅ Service enabled${NC}"
    fi

    echo ""
    echo -e "${GREEN}✅ Systemd service installed${NC}"
    echo ""
    echo "Commands:"
    echo "  - Start:   sudo systemctl start momentum-bot"
    echo "  - Stop:    sudo systemctl stop momentum-bot"
    echo "  - Restart: sudo systemctl restart momentum-bot"
    echo "  - Status:  sudo systemctl status momentum-bot"
    echo "  - Logs:    sudo journalctl -u momentum-bot -f"

    wait_for_user
}

# Option 8: Setup helper modules
setup_helpers() {
    echo -e "${CYAN}Setting up helper modules${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    bash setup_helpers.sh

    wait_for_user
}

# Option 9: Install dependencies
install_deps() {
    echo -e "${CYAN}Installing/Updating dependencies${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    # Check if venv exists
    if [ ! -d "venv" ]; then
        echo "Virtual environment not found. Creating..."
        python3 -m venv venv
        echo -e "${GREEN}✅ Virtual environment created${NC}"
    fi

    echo "Activating virtual environment..."
    source venv/bin/activate

    echo ""
    echo "Installing dependencies from requirements.txt..."
    pip install --upgrade pip
    pip install -r requirements.txt

    echo ""
    echo -e "${GREEN}✅ Dependencies installed${NC}"

    wait_for_user
}

# Main loop
while true; do
    show_menu
    read -p "Select option (0-9): " choice

    case $choice in
        1) clear; run_tests ;;
        2) clear; start_bot_foreground ;;
        3) clear; start_bot_daemon ;;
        4) clear; stop_bot ;;
        5) clear; check_status ;;
        6) clear; view_logs ;;
        7) clear; install_systemd ;;
        8) clear; setup_helpers ;;
        9) clear; install_deps ;;
        0)
            echo ""
            echo -e "${GREEN}👋 Goodbye!${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option. Please try again.${NC}"
            sleep 1
            clear
            ;;
    esac
done
