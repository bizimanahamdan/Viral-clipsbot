# Part 2 Roadmap — Viral Shorts Bot

## Remaining Implementation

### AI Module (ai/)
- [ ] Full Groq LLM integration for viral moment detection
- [ ] Complete title/description/hashtag generation
- [ ] Emoji insertion engine with context awareness
- [ ] Content scoring and ranking system

### Transcription Module (transcription/)
- [ ] Full Whisper API integration with word-level timestamps
- [ ] Audio normalisation pipeline
- [ ] Chunk-based transcription for long videos
- [ ] Language auto-detection

### Video Processing (video_processing/)
- [ ] Complete yt-dlp downloader with progress tracking
- [ ] Advanced clipping with silence removal
- [ ] Full face-tracking auto-reframe (OpenCV integration)
- [ ] Dynamic zoom effect generation
- [ ] B-roll insertion system

### Captions (captions/)
- [ ] Animated word-by-word caption rendering
- [ ] All 5 caption styles fully implemented
- [ ] Custom font loading and fallback chain
- [ ] Caption timing sync with audio
- [ ] SRT/VTT subtitle export

### Pipeline Integration (bot/main.py → full pipeline)
- [ ] Complete end-to-end processing pipeline
- [ ] Progress tracking and status updates
- [ ] Error recovery and retry logic
- [ ] Result delivery via Telegram

### Additional Features
- [ ] YouTube Shorts upload to user's channel
- [ ] Batch processing for multiple URLs
- [ ] User preferences persistence
- [ ] Analytics dashboard

## Dependencies

Part 2 requires the following packages (already in requirements.txt):
- `openai` — Groq-compatible API client
- `yt-dlp` — YouTube downloader
- `opencv-python-headless` — Computer vision
- `pillow` — Image/caption rendering
