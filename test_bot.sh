#!/bin/bash
#
# Momentum Bot - Pre-flight Test Script
# Tests all dependencies and configuration before running the bot
#
# Usage: bash test_bot.sh
#

set -e  # Exit on error

echo "🤖 Momentum Discord Bot - Pre-flight Check"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
ERRORS=0
WARNINGS=0

# Helper functions
error() {
    echo -e "${RED}❌ ERROR: $1${NC}"
    ((ERRORS++))
}

warning() {
    echo -e "${YELLOW}⚠️  WARNING: $1${NC}"
    ((WARNINGS++))
}

success() {
    echo -e "${GREEN}✅ $1${NC}"
}

info() {
    echo -e "ℹ️  $1"
}

# Check if we're in the right directory
echo "📂 Checking directory..."
if [ ! -f "main.py" ]; then
    error "main.py not found. Please run this script from the repository root."
    exit 1
fi
success "Repository root directory confirmed"
echo ""

# Check Python version
echo "🐍 Checking Python installation..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)

    if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 8 ]; then
        success "Python $PYTHON_VERSION (>= 3.8 required)"
    else
        error "Python $PYTHON_VERSION found, but 3.8+ required"
    fi
else
    error "python3 not found in PATH"
fi
echo ""

# Check virtual environment
echo "📦 Checking virtual environment..."
if [ -d "venv" ]; then
    success "Virtual environment exists"

    # Check if venv is activated
    if [[ "$VIRTUAL_ENV" != "" ]]; then
        success "Virtual environment is activated"
    else
        warning "Virtual environment not activated. Activate with: source venv/bin/activate"
    fi
else
    warning "Virtual environment not found. Create with: python3 -m venv venv"
fi
echo ""

# Check Python dependencies
echo "📚 Checking Python dependencies..."
REQUIRED_MODULES=("discord" "pymongo" "pytz")

for module in "${REQUIRED_MODULES[@]}"; do
    if python3 -c "import $module" 2>/dev/null; then
        success "$module installed"
    else
        error "$module not installed (run: pip install -r requirements.txt)"
    fi
done
echo ""

# Check helper modules
echo "🔧 Checking helper modules..."
HELPER_MODULES=("linkdb.py" "emoji.py" "random_msg.py" "images.py" "private.py")

for module in "${HELPER_MODULES[@]}"; do
    if [ -f "$module" ]; then
        success "$module exists"

        # Test if module can be imported
        if python3 -c "import ${module%.py}" 2>/dev/null; then
            success "  └─ ${module} imports successfully"
        else
            error "  └─ ${module} has import errors"
        fi
    else
        error "$module missing (see Claude.MD for setup)"
    fi
done
echo ""

# Check Discord token
echo "🔐 Checking Discord token..."
if [ -f "private.py" ]; then
    TOKEN=$(python3 -c "from private import DISCORD_TOKEN; print(DISCORD_TOKEN)" 2>/dev/null || echo "")

    if [ -z "$TOKEN" ]; then
        error "Could not read DISCORD_TOKEN from private.py"
    elif [ "$TOKEN" = "YOUR_DISCORD_BOT_TOKEN_HERE" ]; then
        error "Discord token is still placeholder. Update private.py with your actual token."
    elif [ ${#TOKEN} -lt 50 ]; then
        warning "Discord token seems too short (${#TOKEN} chars). Typical tokens are 70+ characters."
    else
        success "Discord token configured (${#TOKEN} characters)"
    fi
else
    error "private.py not found"
fi
echo ""

# Check MongoDB configuration
echo "🗄️  Checking MongoDB configuration..."
if [ -f "linkdb.py" ]; then
    # Try to get MONGO_URI
    MONGO_URI=$(python3 -c "
import os
import linkdb
uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
print(uri)
" 2>/dev/null || echo "")

    if [ -n "$MONGO_URI" ]; then
        success "MongoDB URI configured: ${MONGO_URI:0:30}..."
    else
        warning "Could not determine MongoDB URI"
    fi

    # Test MongoDB connection
    echo "  Testing MongoDB connection..."
    if python3 -c "
from linkdb import get_db
try:
    client = get_db()
    client.admin.command('ping')
    print('CONNECTION_SUCCESS')
except Exception as e:
    print(f'CONNECTION_FAILED: {e}')
" 2>/dev/null | grep -q "CONNECTION_SUCCESS"; then
        success "  └─ MongoDB connection successful"
    else
        error "  └─ MongoDB connection failed. Check connection string and network."
    fi
else
    error "linkdb.py not found"
fi
echo ""

# Check config.py
echo "⚙️  Checking configuration..."
if [ -f "config.py" ]; then
    success "config.py exists"

    # Validate config values
    python3 -c "
import config
import sys

errors = []

# Check channel IDs
if not hasattr(config, 'DAILY_CALL_CHANNEL_ID'):
    errors.append('DAILY_CALL_CHANNEL_ID not defined')
if not hasattr(config, 'ACTIVITIES'):
    errors.append('ACTIVITIES not defined')

if errors:
    for err in errors:
        print(f'ERROR: {err}')
    sys.exit(1)
else:
    print('CONFIG_VALID')
" && success "  └─ Configuration validated" || error "  └─ Configuration has issues"
else
    error "config.py not found"
fi
echo ""

# Check cogs
echo "🎮 Checking cogs..."
ACTIVE_COGS=$(python3 -c "
import main
for ext in main.EXTENSIONS:
    print(ext)
" 2>/dev/null || echo "")

if [ -n "$ACTIVE_COGS" ]; then
    COG_COUNT=$(echo "$ACTIVE_COGS" | wc -l)
    success "Found $COG_COUNT active cogs in main.py"

    # Check if cog files exist
    while IFS= read -r cog; do
        COG_FILE="${cog//.//}.py"
        if [ -f "$COG_FILE" ]; then
            echo "  ✓ $cog"
        else
            error "  ✗ $cog (file not found: $COG_FILE)"
        fi
    done <<< "$ACTIVE_COGS"
else
    warning "Could not read EXTENSIONS from main.py"
fi
echo ""

# Check log file permissions
echo "📝 Checking log file..."
if [ -f "bot.log" ]; then
    if [ -w "bot.log" ]; then
        success "bot.log is writable"
    else
        warning "bot.log exists but is not writable"
    fi
else
    info "bot.log doesn't exist (will be created on first run)"
fi
echo ""

# Check .env file (optional)
echo "🔒 Checking .env file (optional)..."
if [ -f ".env" ]; then
    success ".env file exists"

    if grep -q "DISCORD_TOKEN" .env 2>/dev/null; then
        info "  └─ DISCORD_TOKEN found in .env"
    fi
    if grep -q "MONGO_URI" .env 2>/dev/null; then
        info "  └─ MONGO_URI found in .env"
    fi
else
    info ".env file not found (optional, using private.py)"
fi
echo ""

# Summary
echo "=========================================="
echo "📊 Test Summary"
echo "=========================================="

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed! Bot is ready to run.${NC}"
    echo ""
    echo "Start the bot with: bash run_bot.sh"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  $WARNINGS warning(s) found, but bot should run.${NC}"
    echo ""
    echo "Start the bot with: bash run_bot.sh"
    exit 0
else
    echo -e "${RED}❌ $ERRORS error(s) and $WARNINGS warning(s) found.${NC}"
    echo ""
    echo "Please fix the errors above before running the bot."
    echo "See Claude.MD for detailed setup instructions."
    exit 1
fi
