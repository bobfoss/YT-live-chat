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
    source_byte_count INTEGER NOT NULL DEFAULT 0 CHECK (source_byte_count >= 0),
    updated_at TEXT NOT NULL
);
