CREATE TABLE IF NOT EXISTS sidecar_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_stats (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    captured_video_count INTEGER NOT NULL DEFAULT 0 CHECK (captured_video_count >= 0),
    live_capture_count INTEGER NOT NULL DEFAULT 0 CHECK (live_capture_count >= 0),
    replay_capture_count INTEGER NOT NULL DEFAULT 0 CHECK (replay_capture_count >= 0),
    action_count INTEGER NOT NULL DEFAULT 0 CHECK (action_count >= 0),
    message_count INTEGER NOT NULL DEFAULT 0 CHECK (message_count >= 0),
    unique_channel_count INTEGER NOT NULL DEFAULT 0 CHECK (unique_channel_count >= 0),
    source_byte_count INTEGER NOT NULL DEFAULT 0 CHECK (source_byte_count >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_captures (
    capture_id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('live', 'replay')),
    status TEXT NOT NULL CHECK (status IN ('complete', 'partial')),
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_bytes INTEGER NOT NULL CHECK (source_bytes >= 0),
    source_line_count INTEGER NOT NULL CHECK (source_line_count >= 0),
    action_count INTEGER NOT NULL CHECK (action_count >= 0),
    message_count INTEGER NOT NULL CHECK (message_count >= 0),
    author_count INTEGER NOT NULL CHECK (author_count >= 0),
    first_offset_ms INTEGER,
    last_offset_ms INTEGER,
    broadcast_started_at TEXT,
    broadcast_ended_at TEXT,
    broadcast_status_checked_at TEXT,
    yt_dlp_version TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    UNIQUE (video_id, mode, source_sha256)
);

CREATE INDEX IF NOT EXISTS idx_chat_captures_video
ON chat_captures(video_id, completed_at DESC, capture_id DESC);

CREATE TABLE IF NOT EXISTS chat_actions (
    capture_id INTEGER NOT NULL REFERENCES chat_captures(capture_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    video_offset_ms INTEGER,
    action_type TEXT NOT NULL,
    renderer_type TEXT NOT NULL DEFAULT '',
    message_id TEXT NOT NULL DEFAULT '',
    author_channel_id TEXT NOT NULL DEFAULT '',
    author_name TEXT NOT NULL DEFAULT '',
    message_text TEXT NOT NULL DEFAULT '',
    is_message INTEGER NOT NULL DEFAULT 0 CHECK (is_message IN (0, 1)),
    payload_json TEXT NOT NULL,
    PRIMARY KEY (capture_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_chat_actions_offset
ON chat_actions(capture_id, video_offset_ms, sequence);

CREATE INDEX IF NOT EXISTS idx_chat_actions_author_channel
ON chat_actions(author_channel_id, capture_id)
WHERE is_message = 1 AND author_channel_id <> '';

CREATE TABLE IF NOT EXISTS chat_targets (
    video_id TEXT PRIMARY KEY,
    uploader_channel_id TEXT NOT NULL DEFAULT '',
    replay_status TEXT NOT NULL CHECK (
        replay_status IN ('captured', 'not_available', 'unavailable', 'failed')
    ),
    replay_checked_at TEXT NOT NULL,
    latest_capture_id INTEGER REFERENCES chat_captures(capture_id) ON DELETE SET NULL,
    last_error TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
