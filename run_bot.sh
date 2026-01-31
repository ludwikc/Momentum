#!/bin/bash
#
# Momentum Bot - Run Script
# Runs the Discord bot with proper error handling and logging
#
# Usage: bash run_bot.sh [options]
#
# Options:
#   --test       Run pre-flight tests before starting
#   --daemon     Run in background (use with systemd or screen)
#   --verbose    Enable verbose logging
#   --help       Show this help message
#

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$BOT_DIR/bot.log"
ERROR_LOG="$BOT_DIR/error.log"
PID_FILE="$BOT_DIR/bot.pid"

# Parse arguments
RUN_TESTS=false
DAEMON_MODE=false
VERBOSE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --test)
            RUN_TESTS=true
            shift
            ;;
        --daemon)
            DAEMON_MODE=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --help)
            echo "Momentum Discord Bot - Run Script"
            echo ""
            echo "Usage: bash run_bot.sh [options]"
            echo ""
            echo "Options:"
            echo "  --test       Run pre-flight tests before starting"
            echo "  --daemon     Run in background"
            echo "  --verbose    Enable verbose logging"
            echo "  --help       Show this help message"
            echo ""
            echo "Examples:"
            echo "  bash run_bot.sh --test           # Test then run"
            echo "  bash run_bot.sh --daemon         # Run in background"
            echo "  bash run_bot.sh --test --verbose # Test with verbose output"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Banner
echo -e "${BLUE}"
echo "╔════════════════════════════════════════╗"
echo "║   Momentum Discord Bot - Launcher      ║"
echo "╚════════════════════════════════════════╝"
echo -e "${NC}"

# Change to bot directory
cd "$BOT_DIR" || {
    echo -e "${RED}❌ Failed to change to bot directory: $BOT_DIR${NC}"
    exit 1
}

# Run tests if requested
if [ "$RUN_TESTS" = true ]; then
    echo -e "${YELLOW}🧪 Running pre-flight tests...${NC}"
    echo ""

    if bash test_bot.sh; then
        echo ""
        echo -e "${GREEN}✅ Tests passed! Proceeding to start bot...${NC}"
        echo ""
        sleep 2
    else
        echo ""
        echo -e "${RED}❌ Tests failed. Please fix errors before running.${NC}"
        exit 1
    fi
fi

# Check if bot is already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  Bot is already running (PID: $OLD_PID)${NC}"
        echo ""
        read -p "Stop the existing bot and start a new one? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "Stopping existing bot..."
            kill "$OLD_PID" 2>/dev/null
            sleep 2
            rm -f "$PID_FILE"
        else
            echo "Exiting without starting new bot."
            exit 0
        fi
    else
        # PID file exists but process is dead
        rm -f "$PID_FILE"
    fi
fi

# Check if virtual environment exists and activate it
if [ -d "venv" ]; then
    echo -e "${GREEN}📦 Activating virtual environment...${NC}"
    source venv/bin/activate || {
        echo -e "${RED}❌ Failed to activate virtual environment${NC}"
        exit 1
    }
else
    echo -e "${YELLOW}⚠️  Virtual environment not found. Using system Python.${NC}"
fi

# Check Python version
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo -e "${GREEN}🐍 Python version: $PYTHON_VERSION${NC}"

# Display configuration
echo -e "${GREEN}⚙️  Configuration:${NC}"
echo "   Bot directory: $BOT_DIR"
echo "   Log file: $LOG_FILE"
echo "   Error log: $ERROR_LOG"
echo "   Daemon mode: $DAEMON_MODE"
echo "   Verbose: $VERBOSE"
echo ""

# Create log rotation function
rotate_logs() {
    if [ -f "$LOG_FILE" ]; then
        LOG_SIZE=$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null)
        # Rotate if log is larger than 10MB
        if [ "$LOG_SIZE" -gt 10485760 ]; then
            echo "📝 Rotating log file (size: $(($LOG_SIZE / 1048576))MB)"
            mv "$LOG_FILE" "$LOG_FILE.old"
            touch "$LOG_FILE"
        fi
    fi
}

# Rotate logs before starting
rotate_logs

# Function to run the bot
run_bot() {
    echo -e "${GREEN}🚀 Starting Momentum Discord Bot...${NC}"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Set up trap for clean shutdown
    trap cleanup SIGINT SIGTERM

    cleanup() {
        echo ""
        echo ""
        echo -e "${YELLOW}🛑 Shutting down bot...${NC}"
        rm -f "$PID_FILE"
        exit 0
    }

    # Run the bot
    if [ "$VERBOSE" = true ]; then
        python3 main.py 2>&1 | tee -a "$LOG_FILE"
    else
        python3 main.py 2>&1
    fi

    EXIT_CODE=$?

    # Check exit code
    if [ $EXIT_CODE -ne 0 ]; then
        echo ""
        echo -e "${RED}❌ Bot exited with error code: $EXIT_CODE${NC}"
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Bot crashed with exit code $EXIT_CODE" >> "$ERROR_LOG"

        # Show last few lines of log
        if [ -f "$LOG_FILE" ]; then
            echo ""
            echo "Last 20 lines of log:"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            tail -20 "$LOG_FILE"
        fi

        return $EXIT_CODE
    fi
}

# Run in daemon mode or foreground
if [ "$DAEMON_MODE" = true ]; then
    echo -e "${BLUE}🔄 Starting bot in daemon mode...${NC}"

    # Run in background
    nohup python3 main.py >> "$LOG_FILE" 2>&1 &
    BOT_PID=$!

    # Save PID
    echo $BOT_PID > "$PID_FILE"

    # Wait a moment and check if it's still running
    sleep 2
    if ps -p $BOT_PID > /dev/null; then
        echo -e "${GREEN}✅ Bot started successfully (PID: $BOT_PID)${NC}"
        echo ""
        echo "Commands:"
        echo "  - View logs: tail -f $LOG_FILE"
        echo "  - Stop bot: kill $BOT_PID"
        echo "  - Check status: ps -p $BOT_PID"
    else
        echo -e "${RED}❌ Bot failed to start. Check logs:${NC}"
        tail -20 "$LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
else
    # Run in foreground
    run_bot
    EXIT_CODE=$?

    if [ $EXIT_CODE -ne 0 ]; then
        echo ""
        echo -e "${YELLOW}💡 Tip: Check bot.log for detailed error messages${NC}"
        exit $EXIT_CODE
    fi
fi
