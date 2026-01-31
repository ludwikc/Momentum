#!/bin/bash
#
# Momentum Bot - Helper Module Setup Script
#
# This script copies the template helper modules that are already created
# but gitignored. Run this script after cloning the repository.
#
# Usage: bash setup_helpers.sh
#

echo "🤖 Momentum Discord Bot - Helper Modules Setup"
echo "================================================"
echo ""

# Check if we're in the right directory
if [ ! -f "main.py" ]; then
    echo "❌ Error: main.py not found. Please run this script from the repository root."
    exit 1
fi

# Create private.py from example if it doesn't exist
if [ ! -f "private.py" ]; then
    if [ -f "private.py.example" ]; then
        cp private.py.example private.py
        echo "✅ Created private.py from template"
        echo "   ⚠️  Edit private.py and add your Discord bot token!"
    else
        echo "❌ private.py.example not found"
    fi
else
    echo "ℹ️  private.py already exists, skipping"
fi

# Check for other required files
echo ""
echo "Checking helper modules..."

modules=("linkdb.py" "emoji.py" "random_msg.py" "images.py")
all_exist=true

for module in "${modules[@]}"; do
    if [ -f "$module" ]; then
        echo "✅ $module exists"
    else
        echo "❌ $module missing"
        all_exist=false
    fi
done

if [ "$all_exist" = false ]; then
    echo ""
    echo "⚠️  Some helper modules are missing!"
    echo "   These should have been created when you cloned the repo."
    echo "   Please check the Claude.MD documentation for manual setup."
fi

# Check requirements.txt
echo ""
if [ -f "requirements.txt" ]; then
    echo "✅ requirements.txt exists"
else
    echo "❌ requirements.txt missing"
    echo "   Create it or refer to Claude.MD for dependencies"
fi

# Check .env file
echo ""
if [ -f ".env" ]; then
    echo "✅ .env exists"
else
    echo "⚠️  .env not found (optional)"
    echo "   You can create .env with: DISCORD_TOKEN=your_token_here"
fi

echo ""
echo "================================================"
echo "Next steps:"
echo "1. Edit private.py and add your Discord bot token"
echo "2. Configure MongoDB URI in linkdb.py or .env"
echo "3. Install dependencies: pip install -r requirements.txt"
echo "4. Run the bot: python main.py"
echo ""
echo "📖 For detailed setup instructions, see Claude.MD"
echo "================================================"
