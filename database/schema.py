"""
Database schema definitions for the Viral Shorts Bot.

Contains all CREATE TABLE statements and index definitions
used to initialise the SQLite database.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Users table — stores Telegram user information
# ---------------------------------------------------------------------------
USERS_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    last_name       TEXT,
    language_code   TEXT DEFAULT 'en',
    is_admin        INTEGER DEFAULT 0,
    is_banned       INTEGER DEFAULT 0,
    is_premium      INTEGER DEFAULT 0,
    plan            TEXT DEFAULT 'free',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_active_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# ---------------------------------------------------------------------------
# User settings table — per-user preferences
# ---------------------------------------------------------------------------
USER_SETTINGS_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS user_settings (
    user_id                 INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    num_shorts              INTEGER DEFAULT 3,
    caption_style           TEXT DEFAULT 'hormozi',
    caption_font            TEXT DEFAULT 'montserrat',
    caption_color           TEXT DEFAULT '#FFFFFF',
    caption_highlight_color TEXT DEFAULT '#FFD700',
    emoji_enabled           INTEGER DEFAULT 1,
    zoom_enabled            INTEGER DEFAULT 1,
    broll_enabled           INTEGER DEFAULT 0,
    silence_removal         INTEGER DEFAULT 1,
    output_quality          TEXT DEFAULT 'high',
    language                TEXT DEFAULT 'auto',
    viral_detection_mode    TEXT DEFAULT 'top_3',
    auto_upload             INTEGER DEFAULT 1,
    delete_temp_files       INTEGER DEFAULT 1,
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# ---------------------------------------------------------------------------
# Jobs table — processing job queue
# ---------------------------------------------------------------------------
JOBS_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id              TEXT PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    source_type         TEXT NOT NULL CHECK (source_type IN ('youtube', 'upload')),
    source_url          TEXT,
    source_file_path    TEXT,
    source_filename     TEXT,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'downloading', 'transcribing',
                                         'analyzing', 'clipping', 'processing',
                                         'uploading', 'completed', 'failed', 'cancelled')),
    progress            INTEGER DEFAULT 0,
    progress_message    TEXT,
    num_shorts_requested INTEGER DEFAULT 3,
    settings_snapshot   TEXT,  -- JSON of settings at job creation time
    error_message       TEXT,
    started_at          TEXT,
    completed_at        TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# ---------------------------------------------------------------------------
# History table — completed shorts linked to jobs
# ---------------------------------------------------------------------------
HISTORY_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS history (
    history_id          TEXT PRIMARY KEY,
    job_id              TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    user_id             INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    source_url          TEXT,
    source_filename     TEXT,
    short_index         INTEGER NOT NULL,
    title               TEXT,
    description         TEXT,
    hashtags            TEXT,
    hook                TEXT,
    pinned_comment      TEXT,
    output_file_path    TEXT,
    thumbnail_path      TEXT,
    srt_file_path       TEXT,
    transcript_path     TEXT,
    duration_seconds    REAL,
    viral_score         REAL,
    telegram_message_id INTEGER,
    telegram_file_id    TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# ---------------------------------------------------------------------------
# Statistics table — aggregate usage statistics
# ---------------------------------------------------------------------------
STATISTICS_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS statistics (
    stat_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    event_type          TEXT NOT NULL CHECK (event_type IN (
        'job_created', 'job_completed', 'job_failed', 'job_cancelled',
        'short_generated', 'command_used', 'setting_changed',
        'file_uploaded', 'video_downloaded', 'transcription_done',
        'caption_generated', 'viral_analysis_done'
    )),
    details             TEXT,  -- JSON with extra context
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# ---------------------------------------------------------------------------
# Cache table — stores cached results to avoid redundant processing
# ---------------------------------------------------------------------------
CACHE_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS cache (
    cache_key           TEXT PRIMARY KEY,
    cache_value         TEXT,
    cache_type          TEXT NOT NULL DEFAULT 'json',
    expires_at          TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# ---------------------------------------------------------------------------
# Indexes for performance
# ---------------------------------------------------------------------------
INDEXES_SQL: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);",
    "CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_history_user_id ON history(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_history_job_id ON history(job_id);",
    "CREATE INDEX IF NOT EXISTS idx_statistics_user_id ON statistics(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_statistics_event_type ON statistics(event_type);",
    "CREATE INDEX IF NOT EXISTS idx_statistics_created_at ON statistics(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_cache_expires_at ON cache(expires_at);",
]

# ---------------------------------------------------------------------------
# Combined schema — all statements in dependency order
# ---------------------------------------------------------------------------
ALL_SCHEMA_STATEMENTS: list[str] = [
    USERS_TABLE_SQL,
    USER_SETTINGS_TABLE_SQL,
    JOBS_TABLE_SQL,
    HISTORY_TABLE_SQL,
    STATISTICS_TABLE_SQL,
    CACHE_TABLE_SQL,
    *INDEXES_SQL,
]
