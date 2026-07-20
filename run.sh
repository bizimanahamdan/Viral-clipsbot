#!/usr/bin/env bash
# Viral Shorts Bot — Quick Run Script
set -euo pipefail

# Check if .env exists
if [ ! -f .env ]; then
    echo "ERROR: .env file not found."
    echo "Copy .env.example to .env and fill in your credentials."
    exit 1
fi

# Activate virtual environment if it exists
if [ -d venv ]; then
    source venv/bin/activate
fi

# Run the bot
echo "=== Starting Viral Shorts Bot ==="
python -m bot.main
