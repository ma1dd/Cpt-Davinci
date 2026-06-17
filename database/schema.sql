CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    name TEXT,
    age INTEGER,
    real_age INTEGER,
    city TEXT,
    bio_text TEXT,
    hobbies TEXT,
    raw_text TEXT NOT NULL,
    content_hash TEXT,
    search_text TEXT,
    word_count INTEGER NOT NULL DEFAULT 0,
    min_detected_age INTEGER,
    max_detected_age INTEGER,
    age_values TEXT,
    trash_score REAL,
    trash_label TEXT,
    trash_tags TEXT,
    trash_analysis_version INTEGER NOT NULL DEFAULT 0,
    mutual_like INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS profile_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    message_id INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    file_id TEXT,
    file_unique_id TEXT,
    local_path TEXT,
    face_count INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    reaction_type TEXT NOT NULL,
    comment_text TEXT,
    callback_data TEXT,
    source_message_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source_message_id)
);

CREATE INDEX IF NOT EXISTS idx_profiles_chat_message ON profiles (chat_id, message_id);
CREATE INDEX IF NOT EXISTS idx_reactions_profile ON reactions (profile_id);
