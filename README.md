# Viral Shorts Bot

A production-quality Telegram bot that converts long YouTube videos or uploaded MP4 files into viral short-form videos (9:16 format) with AI-powered viral moment detection, animated captions, emoji overlays, B-roll, and zoom effects.

---

## Features

| Feature | Description |
|---------|-------------|
| YouTube Download | Download videos from YouTube URLs via yt-dlp (1080p, retries, playlist rejection) |
| File Upload | Accept MP4, MOV, AVI, MKV video uploads up to 2GB |
| Audio Extraction | Extract and normalize audio using FFmpeg (volume normalization, noise reduction) |
| Whisper Transcription | Groq Whisper API for fast, accurate transcription with word-level timestamps |
| Viral Detection | LLM-powered analysis scoring hooks, emotional moments, humor, storytelling, retention |
| Auto Clipping | Intelligent clipping at viral moments with silence removal and smooth transitions |
| 9:16 Auto-Reframe | Face-tracking camera reframe from landscape to portrait using OpenCV Haar Cascades |
| Animated Captions | Word-by-word TikTok-style captions with 5 styles (Hormozi, Clean, Minimal, Karaoke, Typewriter) |
| Emoji Overlays | Context-aware emoji insertion based on transcript analysis (money, fire, shock, love, etc.) |
| Zoom Effects | Motion-based zoom points detected via optical flow analysis |
| B-roll Engine | Overlay stock B-roll from configurable local folders with smart category matching |
| Viral Titles | AI-generated viral titles, descriptions, hashtags, hooks, and pinned comment suggestions |
| Multi-Short Output | Generate 1-10 shorts from a single video source |
| Queue System | Async job queue supporting multiple concurrent users with progress tracking |
| Admin Panel | Bot stats, user management, broadcast, cache cleanup, restart, logs |
| Database | SQLite with users, settings, history, jobs, and statistics tables |
| Security | Rate limiting, file validation, input sanitization, admin authentication |

---

## Project Structure

```
viral-shorts-bot/
├── bot/                    # Bot entry point and initialization
│   ├── __init__.py
│   └── main.py             # Main entry point, handler registration, polling
├── ai/                     # AI/LLM modules
│   ├── __init__.py
│   ├── viral_detector.py   # Viral moment detection via Groq LLM
│   ├── title_generator.py  # Viral title/description/hashtag generation
│   ├── emoji_engine.py     # Context-aware emoji insertion
│   └── groq_client.py      # Groq API client wrapper
├── transcription/          # Audio transcription pipeline
│   ├── __init__.py
│   ├── extractor.py        # FFmpeg audio extraction + normalization
│   └── whisper.py          # Groq Whisper API transcription
├── video_processing/       # Video processing pipeline
│   ├── __init__.py
│   ├── downloader.py       # yt-dlp YouTube downloader
│   ├── clipping.py         # Video clipping + silence removal
│   ├── reframe.py          # 9:16 face-tracking auto-reframe
│   ├── output.py           # Final render compositing
│   └── broll.py            # B-roll overlay engine
├── captions/               # Caption generation
│   ├── __init__.py
│   └── generator.py        # Animated word-by-word caption frames
├── ffmpeg_utils/           # FFmpeg utilities
│   ├── __init__.py
│   ├── commands.py         # FFmpeg command executor + metadata
│   └── processor.py        # High-level FFmpeg operations
├── opencv_utils/           # OpenCV utilities
│   ├── __init__.py
│   ├── face_tracker.py     # Haar Cascade face detection + tracking
│   └── motion_detector.py  # Motion/scene/camera analysis
├── pipeline/               # End-to-end orchestration
│   ├── __init__.py
│   └── processor.py        # Full pipeline orchestrator
├── telegram_handlers/      # Telegram command/message handlers
│   ├── __init__.py
│   ├── common.py           # Shared utilities
│   ├── commands.py         # /start, /help, /settings, /history, etc.
│   ├── callbacks.py        # Inline button callbacks
│   └── messages.py         # URL and file upload handlers
├── database/               # SQLite database
│   ├── __init__.py
│   ├── schema.py           # Table definitions
│   ├── connection.py       # Connection pool
│   ├── users.py            # User CRUD
│   ├── settings.py         # Settings CRUD
│   ├── jobs.py             # Job queue CRUD
│   ├── history.py          # History CRUD
│   └── statistics.py       # Statistics CRUD
├── utilities/              # Shared utilities
│   ├── __init__.py
│   ├── logging_config.py   # Rich logging configuration
│   ├── security.py         # Rate limiting, validation, sanitization
│   └── queue_manager.py    # Async job queue
├── configuration/          # Configuration
│   ├── __init__.py
│   └── config.py           # Environment-based configuration
├── tests/                  # Unit tests
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_database.py
│   ├── test_queue.py
│   └── test_security.py
├── deployment/             # Deployment files
│   ├── __init__.py
│   ├── Dockerfile
│   └── docker-compose.yml
├── documentation/          # Documentation
│   ├── __init__.py
│   ├── SETUP.md
│   └── PART2_ROADMAP.md
├── .env.example            # Environment variable template
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── setup.sh                # Quick setup script
└── run.sh                  # Quick run script
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- FFmpeg 5.0+
- OpenCV (`libopencv-dev` for face detection)
- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- A Groq API Key (from [console.groq.com](https://console.groq.com))

### 1. Clone and Setup

```bash
# Clone the project
git clone <your-repo>
cd viral-shorts-bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
nano .env  # Edit with your tokens
```

### 2. Configure Environment

Edit `.env` with your credentials:

```env
# Required
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
GROQ_API_KEY=gsk_YourGroqApiKeyHere

# Admin
ADMIN_IDS=123456789,987654321

# Optional
MAX_SHORTS_PER_REQUEST=5
MAX_VIDEO_SIZE_MB=2048
OUTPUT_QUALITY=high
BROLL_DIRS=/path/to/broll/folder1,/path/to/broll/folder2
```

### 3. Run the Bot

```bash
# Direct run
python -m bot.main

# Or using the script
chmod +x run.sh
./run.sh
```

### 4. Docker Deployment

```bash
cd deployment
docker-compose build
docker-compose up -d
```

---

## Termux Setup (Android)

```bash
# Install Termux dependencies
pkg update && pkg upgrade
pkg install python ffmpeg libjpeg-turbo libpng libwebp

# Install OpenCV via pip (slower but works)
pip install opencv-python-headless

# Setup the bot
cd viral-shorts-bot
pip install -r requirements.txt
cp .env.example .env
nano .env

# Run
python -m bot.main
```

> **Note:** Termux has limited CPU/RAM. Reduce `MAX_SHORTS_PER_REQUEST=1` and set `OUTPUT_QUALITY=medium` for best results.

---

## Usage Guide

### Basic Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with main menu |
| `/help` | Help with usage instructions |
| `/settings` | Configure output preferences |
| `/history` | View your processing history |
| `/queue` | Check your position in the queue |
| `/account` | View account statistics |

### Creating a Short

1. Send a **YouTube URL** — the bot will download and process it
2. Send a **video file** (MP4, MOV, AVI, MKV) — the bot will process it directly
3. Use **/settings** to customize output (caption style, emoji, zoom, B-roll, quality)
4. The bot generates 1-N viral shorts and sends them back

### Settings Options

| Setting | Values | Default |
|---------|--------|---------|
| Number of Shorts | 1-10 | 3 |
| Caption Style | Hormozi, Clean, Minimal, Karaoke, Typewriter | Hormozi |
| Caption Color | White, Yellow, Green, Red, Blue, Custom | White |
| Font Size | Small, Medium, Large | Large |
| Emoji | On / Off | On |
| Zoom Effect | On / Off | On |
| B-roll | On / Off | On |
| Silence Removal | On / Off | On |
| Output Quality | High, Medium, Low | High |
| Language | Auto, English, Spanish, Arabic, etc. | Auto |
| Viral Detection | Aggressive, Balanced, Conservative | Balanced |

### Admin Commands

| Command | Description |
|---------|-------------|
| `/stats` | Bot statistics (users, jobs, processing) |
| `/users` | List all registered users |
| `/broadcast` | Send message to all users |
| `/cache` | Clear temporary files |
| `/cleanup` | Clean old data files |
| `/restart` | Restart the bot |
| `/logs` | View recent bot logs |

---

## B-roll Setup

The B-roll engine overlays stock footage from local folders organized by category:

```
broll/
├── money/
│   ├── finance_1.mp4
│   └── cash_2.mp4
├── tech/
│   ├── computer_1.mp4
│   └── phone_2.mp4
├── nature/
│   ├── ocean_1.mp4
│   └── sunset_2.mp4
├── city/
│   └── street_1.mp4
├── people/
│   └── typing_1.mp4
└── abstract/
    └── particles_1.mp4
```

Configure B-roll directories in `.env`:
```env
BROLL_DIRS=/home/user/broll,/mnt/storage/broll
```

---

## Configuration Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token | (required) |
| `GROQ_API_KEY` | Groq API key for LLM + Whisper | (required) |
| `ADMIN_IDS` | Comma-separated admin user IDs | (required) |
| `MAX_SHORTS_PER_REQUEST` | Max shorts per request | 5 |
| `MAX_VIDEO_SIZE_MB` | Max upload size in MB | 2048 |
| `MAX_VIDEO_DURATION_MIN` | Max video duration in minutes | 120 |
| `OUTPUT_QUALITY` | Default output quality | high |
| `CAPTION_STYLE` | Default caption style | hormozi |
| `CAPTION_FONT_PATH` | Path to caption font file | system default |
| `CAPTION_FONT_SIZE` | Default font size | 64 |
| `CAPTION_COLOR` | Default caption color | #FFFFFF |
| `CAPTION_HIGHLIGHT_COLOR` | Highlighted word color | #FFD700 |
| `EMOJI_ENABLED` | Default emoji setting | true |
| `ZOOM_ENABLED` | Default zoom setting | true |
| `BROLL_ENABLED` | Default B-roll setting | true |
| `SILENCE_REMOVAL` | Default silence removal | true |
| `BROLL_DIRS` | Comma-separated B-roll directories | (empty) |
| `RATE_LIMIT_WINDOW` | Rate limit window in seconds | 60 |
| `RATE_LIMIT_MAX_REQUESTS` | Max requests per window | 10 |
| `TEMP_DIR` | Temporary files directory | ./data/temp |
| `OUTPUTS_DIR` | Output files directory | ./data/outputs |
| `UPLOADS_DIR` | Upload files directory | ./data/uploads |
| `LOG_LEVEL` | Logging level | INFO |

---

## Deployment

### Linux Server

```bash
# Install dependencies
sudo apt update
sudo apt install -y python3.11 python3.11-venv ffmpeg libopencv-dev

# Setup
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure systemd service
sudo tee /etc/systemd/system/viral-shorts-bot.service << 'EOF'
[Unit]
Description=Viral Shorts Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/viral-shorts-bot
Environment="PATH=/home/ubuntu/viral-shorts-bot/venv/bin"
ExecStart=/home/ubuntu/viral-shorts-bot/venv/bin/python -m bot.main
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable viral-shorts-bot
sudo systemctl start viral-shorts-bot
sudo systemctl status viral-shorts-bot
```

### Docker

```bash
# Build and run
cd deployment
docker-compose build
docker-compose up -d

# View logs
docker-compose logs -f bot

# Stop
docker-compose down
```

---

## API Keys

### Telegram Bot Token

1. Open Telegram and find [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow instructions
3. Copy the token

### Groq API Key

1. Visit [console.groq.com](https://console.groq.com)
2. Create an account and get your API key
3. Groq provides free credits for LLM and Whisper API access

---

## Development

### Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test module
python -m pytest tests/test_database.py -v

# With coverage
pip install pytest-cov
python -m pytest tests/ --cov=. --cov-report=html
```

### Adding New Caption Styles

1. Edit `captions/generator.py` — add a new style dict to `CAPTION_STYLES`
2. Define: `font_size`, `bold`, `stroke`, `shadow`, `background_box`, `highlight_current`, `max_words_per_line`, `position`

### Adding New Viral Detection Criteria

1. Edit `ai/viral_detector.py` — add criteria to the prompt template
2. Define scoring weights in `VIRAL_CRITERIA`

---

## License

This project is provided as-is for educational and personal use.

---

## Changelog

### Part 2 (Current)
- Full AI pipeline: viral detection, title generation, emoji engine
- Full transcription: FFmpeg extraction + Groq Whisper
- Full video processing: download, clip, reframe, output, B-roll
- Full captions: animated word-by-word with 5 styles
- Full OpenCV: face tracking, motion detection
- Full FFmpeg processor: silence removal, scene detection, composition
- End-to-end pipeline orchestrator

### Part 1 (Previous)
- Project structure and configuration
- Database module (SQLite)
- Queue system (async, multi-user)
- Telegram handlers (commands, callbacks, messages)
- Security module (rate limiting, validation)
- Logging with Rich
- Admin panel commands
- Docker deployment files
