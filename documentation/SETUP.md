# Viral Shorts Bot — Setup Guide

## Prerequisites

- Python 3.11+
- FFmpeg 5.0+
- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- A Groq API Key (from [console.groq.com](https://console.groq.com))

## Quick Start

```bash
# 1. Clone and install
cd /home/ubuntu/viral-shorts-bot
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your credentials

# 3. Run
python -m bot.main
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | Required |
| `TELEGRAM_ADMIN_IDS` | Comma-separated admin user IDs | `""` |
| `GROQ_API_KEY` | Groq API key for Whisper + LLM | Required |
| `ADMIN_IDS` | Same as TELEGRAM_ADMIN_IDS | `""` |

### Default Settings

The bot uses sensible defaults for all settings. Users can customise:

- Number of Shorts (1–20)
- Caption style (hormozi, clean, minimal, karaoke, typewriter)
- Caption font and color
- Emoji on/off
- Dynamic zoom on/off
- B-roll on/off
- Silence removal on/off
- Output quality (low, medium, high, ultra)
- Language (auto-detect or specific)
- Viral detection mode (top 3/5/10)
- Auto-upload on/off
- Delete temp files on/off

## Architecture

```
viral-shorts-bot/
├── bot/                    # Bot entry point
├── ai/                     # Groq AI integration
├── transcription/          # Audio extraction + Whisper
├── video_processing/       # Download, clip, reframe, output
├── captions/               # Caption generation
├── ffmpeg_utils/           # FFmpeg wrappers
├── opencv_utils/           # Face tracking, motion detection
├── telegram_handlers/      # Telegram handlers
├── database/               # SQLite database
├── utilities/              # Queue, security, logging
├── configuration/          # Config loading
├── tests/                  # Test suite
├── deployment/             # Docker files
└── documentation/          # This guide
```

## Processing Pipeline

1. **Input** — YouTube URL or MP4 upload
2. **Download** — yt-dlp downloads the video
3. **Extract Audio** — FFmpeg extracts audio track
4. **Transcribe** — Groq Whisper transcribes audio
5. **Detect Viral Moments** — Groq LLM analyses transcript
6. **Generate Captions** — AI creates titles, hashtags, captions
7. **Clip Segments** — FFmpeg clips each viral moment
8. **Reframe** — Convert to 9:16 vertical format
9. **Add Captions** — Burn-in animated word-by-word captions
10. **Final Output** — Generate final video with all effects
11. **Deliver** — Send to user via Telegram

## Docker Deployment

```bash
cd deployment
docker-compose up -d
```

## Rate Limits

- 10 requests per minute per user
- Maximum 2 concurrent jobs per user
- Maximum file size: 2 GB
- Maximum YouTube video length: 1 hour

## Admin Commands

| Command | Description |
|---|---|
| `/stats` | View global statistics |
| `/users` | List all users |
| `/broadcast` | Send message to all users |
| `/cache` | View cache status |
| `/cleanup` | Clean up old files |
| `/restart` | Restart the bot |
| `/logs` | View recent logs |
