#!/usr/bin/env bash
# Viral Shorts Bot — Quick Setup Script
set -euo pipefail

echo "=== Viral Shorts Bot Setup ==="
echo ""

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3.11+ is required but not found."
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $PYTHON_VERSION"

# Check FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "ERROR: FFmpeg is required but not found."
    echo "Install with: sudo apt install ffmpeg (Ubuntu/Debian)"
    echo "              brew install ffmpeg (macOS)"
    exit 1
fi
echo "FFmpeg version: $(ffmpeg -version 2>&1 | head -1)"

# Create virtual environment
echo ""
echo "--- Creating virtual environment ---"
python3 -m venv venv
source venv/bin/activate

# Install dependencies
echo ""
echo "--- Installing Python dependencies ---"
pip install --upgrade pip
pip install -r requirements.txt

# Configure environment
if [ ! -f .env ]; then
    echo ""
    echo "--- Creating .env file ---"
    cp .env.example .env
    echo "Edit .env with your Telegram Bot Token and Groq API Key"
fi

# Create data directories
echo ""
echo "--- Creating data directories ---"
mkdir -p data/uploads data/outputs data/temp data/captions data/broll

# Verify installation
echo ""
echo "--- Verifying installation ---"
python -c "
import sys
print(f'Python: {sys.version}')
try:
    from telegram import Bot
    print('telegram: OK')
except ImportError:
    print('telegram: MISSING')
try:
    import cv2
    print(f'opencv: OK (v{cv2.__version__})')
except ImportError:
    print('opencv: MISSING (face tracking disabled)')
try:
    from rich import print
    print('rich: OK')
except ImportError:
    print('rich: MISSING')
"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your TELEGRAM_BOT_TOKEN and GROQ_API_KEY"
echo "  2. Run: python -m bot.main"
echo ""
