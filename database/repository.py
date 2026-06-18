import sqlite3
from dataclasses import dataclass
from pathlib import Path

from services.media_fingerprint import (
    build_content_hash,
    fingerprint_file,
    resolve_stored_media_path,
)
from services.profile_text_analysis import analyze_profile_text, extra_search_tokens

_ANALYSIS_VERSION = 1


@dataclass
class ProfileStats:
    profiles: int
    likes: int
    dislikes: int
    comments: int
    mutual_likes: int


def build_search_text(
    *,
    name: str | None,
    age: int | None,
    city: str | None,
    bio_text: str | None,
    hobbies: str | None,
    raw_text: str,
    real_age: int | None = None,
) -> str:
    analysis = analyze_profile_text(age=age, real_age=real_age, raw_text=raw_text)
    parts = [
        name,
        city,
        bio_text,
        hobbies,
        raw_text,
        str(age) if age is not None else "",
        str(real_age) if real_age is not None else "",
        extra_search_tokens(analysis),
    ]
    return " ".join(part.strip() for part in parts if part and part.strip()).casefold()


class ProfileRepository:
    def __init__(self, db_path: Path, base_dir: Path | None = None) -> None:
        self.db_path = db_path
        self.base_dir = base_dir or db_path.resolve().parent.parent

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(profiles)").fetchall()
        }
        if "content_hash" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN content_hash TEXT")
        if "search_text" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN search_text TEXT")
        if "mutual_like" not in columns:
            conn.execute(
                "ALTER TABLE profiles ADD COLUMN mutual_like INTEGER NOT NULL DEFAULT 0"
            )
        if "word_count" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN word_count INTEGER NOT NULL DEFAULT 0")
        if "min_detected_age" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN min_detected_age INTEGER")
        if "max_detected_age" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN max_detected_age INTEGER")
        if "age_values" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN age_values TEXT")
        if "analysis_version" not in columns:
            conn.execute(
                "ALTER TABLE profiles ADD COLUMN analysis_version INTEGER NOT NULL DEFAULT 0"
            )
        if "trash_score" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN trash_score REAL")
        if "trash_label" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN trash_label TEXT")
        if "trash_tags" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN trash_tags TEXT")
        if "trash_analysis_version" not in columns:
            conn.execute(
                "ALTER TABLE profiles ADD COLUMN trash_analysis_version INTEGER NOT NULL DEFAULT 0"
            )
        if "detected_signals" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN detected_signals TEXT")

        media_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(profile_media)").fetchall()
        }
        if "file_unique_id" not in media_columns:
            conn.execute("ALTER TABLE profile_media ADD COLUMN file_unique_id TEXT")
        if "face_count" not in media_columns:
            conn.execute("ALTER TABLE profile_media ADD COLUMN face_count INTEGER")

        reaction_indexes = conn.execute(
            "PRAGMA index_list(reactions)"
        ).fetchall()
        index_names = {row["name"] for row in reaction_indexes}
        if "idx_reactions_source_message" not in index_names:
            try:
                conn.execute(
                    """
                    CREATE UNIQUE INDEX idx_reactions_source_message
                    ON reactions(source_message_id)
                    WHERE source_message_id IS NOT NULL
                    """
                )
            except sqlite3.OperationalError:
                pass

        rows = conn.execute(
            """
            SELECT id, name, age, real_age, city, bio_text, hobbies, raw_text, search_text
            FROM profiles
            """
        ).fetchall()
        for row in rows:
            media_fingerprints = self._media_fingerprints_for_profile(conn, int(row["id"]))
            content_hash = build_content_hash(
                name=row["name"],
                age=row["age"],
                raw_text=row["raw_text"],
                media_fingerprints=media_fingerprints,
            )
            analysis = analyze_profile_text(
                age=row["age"],
                real_age=row["real_age"],
                raw_text=row["raw_text"],
            )
            search_text = build_search_text(
                name=row["name"],
                age=row["age"],
                city=row["city"],
                bio_text=row["bio_text"],
                hobbies=row["hobbies"],
                raw_text=row["raw_text"],
                real_age=row["real_age"],
            )
            conn.execute(
                """
                UPDATE profiles
                SET content_hash = ?,
                    search_text = ?,
                    word_count = ?,
                    min_detected_age = ?,
                    max_detected_age = ?,
                    age_values = ?,
                    analysis_version = ?
                WHERE id = ?
                """,
                (
                    content_hash,
                    search_text,
                    analysis.word_count,
                    analysis.min_detected_age,
                    analysis.max_detected_age,
                    analysis.age_values,
                    _ANALYSIS_VERSION,
                    row["id"],
                ),
            )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_profiles_content_hash ON profiles(content_hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_profiles_search_text ON profiles(search_text)"
        )

    def _media_fingerprints_for_profile(
        self,
        conn: sqlite3.Connection,
        profile_id: int,
    ) -> list[str]:
        rows = conn.execute(
            """
            SELECT local_path, file_id, file_unique_id, media_type, sort_order
            FROM profile_media
            WHERE profile_id = ?
            ORDER BY sort_order, id
            """,
            (profile_id,),
        ).fetchall()

        fingerprints: list[str] = []
        for row in rows:
            path = resolve_stored_media_path(row["local_path"], self.base_dir)
            file_hash = fingerprint_file(path) if path else None
            if file_hash:
                fingerprints.append(file_hash)
                continue

            if row["file_unique_id"]:
                fingerprints.append(
                    f"{row['media_type']}:{row['file_unique_id']}"
                )
            elif row["file_id"]:
                fingerprints.append(f"file_id:{row['file_id']}")

        return sorted(fingerprints)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def profile_exists(self, chat_id: int, message_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM profiles WHERE chat_id = ? AND message_id = ?",
                (chat_id, message_id),
            ).fetchone()
        return row is not None

    def get_profile_id_by_content_hash(self, content_hash: str) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM profiles
                WHERE content_hash = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (content_hash,),
            ).fetchone()
        return int(row["id"]) if row else None

    def find_profile_id_by_identity(
        self,
        *,
        name: str | None,
        age: int | None,
        content_hash: str | None = None,
    ) -> int | None:
        if content_hash:
            found = self.get_profile_id_by_content_hash(content_hash)
            if found is not None:
                return found

        if not name or age is None:
            return None

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM profiles
                WHERE LOWER(COALESCE(name, '')) = LOWER(?)
                  AND age = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (name, age),
            ).fetchone()
        return int(row["id"]) if row else None

    def set_mutual_like(self, profile_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE profiles SET mutual_like = 1 WHERE id = ?",
                (profile_id,),
            )

    def set_mutual_like_by_content_hash(self, content_hash: str) -> int | None:
        profile_id = self.get_profile_id_by_content_hash(content_hash)
        if profile_id is None:
            return None
        self.set_mutual_like(profile_id)
        return profile_id

    def create_profile(
        self,
        *,
        message_id: int,
        chat_id: int,
        name: str | None,
        age: int | None,
        real_age: int | None,
        city: str | None,
        bio_text: str | None,
        hobbies: str | None,
        raw_text: str,
        content_hash: str,
        search_text: str,
        word_count: int = 0,
        min_detected_age: int | None = None,
        max_detected_age: int | None = None,
        age_values: str | None = None,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO profiles (
                    message_id, chat_id, name, age, real_age,
                    city, bio_text, hobbies, raw_text, content_hash, search_text,
                    word_count, min_detected_age, max_detected_age, age_values,
                    analysis_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    chat_id,
                    name,
                    age,
                    real_age,
                    city,
                    bio_text,
                    hobbies,
                    raw_text,
                    content_hash,
                    search_text,
                    word_count,
                    min_detected_age,
                    max_detected_age,
                    age_values,
                    _ANALYSIS_VERSION,
                ),
            )
            return int(cursor.lastrowid)

    def add_media(
        self,
        *,
        profile_id: int,
        message_id: int,
        media_type: str,
        file_id: str | None,
        file_unique_id: str | None,
        local_path: str | None,
        sort_order: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO profile_media (
                    profile_id, message_id, media_type, file_id,
                    file_unique_id, local_path, sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    message_id,
                    media_type,
                    file_id,
                    file_unique_id,
                    local_path,
                    sort_order,
                ),
            )

    def update_profile_trash(
        self,
        profile_id: int,
        *,
        trash_score: float,
        trash_label: str,
        trash_tags: str,
        trash_analysis_version: int,
        detected_signals: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE profiles
                SET trash_score = ?,
                    trash_label = ?,
                    trash_tags = ?,
                    trash_analysis_version = ?,
                    detected_signals = COALESCE(?, detected_signals)
                WHERE id = ?
                """,
                (
                    trash_score,
                    trash_label,
                    trash_tags,
                    trash_analysis_version,
                    detected_signals,
                    profile_id,
                ),
            )

    def set_media_face_count(
        self,
        profile_id: int,
        sort_order: int,
        face_count: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE profile_media
                SET face_count = ?
                WHERE profile_id = ? AND sort_order = ?
                """,
                (face_count, profile_id, sort_order),
            )

    def get_profile_media_rows(self, profile_id: int) -> list[tuple[str, str | None, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT media_type, local_path, sort_order
                FROM profile_media
                WHERE profile_id = ?
                ORDER BY sort_order, id
                """,
                (profile_id,),
            ).fetchall()
        return [(row["media_type"], row["local_path"], int(row["sort_order"])) for row in rows]

    def get_profile_id_by_message(self, chat_id: int, message_id: int) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM profiles WHERE chat_id = ? AND message_id = ?",
                (chat_id, message_id),
            ).fetchone()
        return int(row["id"]) if row else None

    def get_latest_profile_id(self, chat_id: int) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM profiles
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (chat_id,),
            ).fetchone()
        return int(row["id"]) if row else None

    def get_latest_unreacted_profile_id(self, chat_id: int) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT p.id
                FROM profiles p
                WHERE p.chat_id = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM reactions r
                      WHERE r.profile_id = p.id
                  )
                ORDER BY p.id DESC
                LIMIT 1
                """,
                (chat_id,),
            ).fetchone()
        return int(row["id"]) if row else None

    def reaction_source_exists(self, source_message_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM reactions WHERE source_message_id = ?",
                (source_message_id,),
            ).fetchone()
        return row is not None

    def delete_all_reactions(self) -> int:
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM reactions").fetchone()["c"]
            conn.execute("DELETE FROM reactions")
        return int(count)

    def add_reaction(
        self,
        *,
        profile_id: int,
        reaction_type: str,
        comment_text: str | None = None,
        callback_data: str | None = None,
        source_message_id: int | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO reactions (
                    profile_id, reaction_type, comment_text, callback_data, source_message_id
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    reaction_type,
                    comment_text,
                    callback_data,
                    source_message_id,
                ),
            )

    def get_stats(self) -> ProfileStats:
        with self._connect() as conn:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(profiles)").fetchall()
            }
            if "mutual_like" not in columns:
                conn.execute(
                    "ALTER TABLE profiles ADD COLUMN mutual_like INTEGER NOT NULL DEFAULT 0"
                )
            profiles = conn.execute("SELECT COUNT(*) AS c FROM profiles").fetchone()["c"]
            likes = conn.execute(
                """
                SELECT COUNT(DISTINCT profile_id) AS c
                FROM reactions r
                WHERE r.reaction_type = 'like'
                   OR (
                        r.reaction_type = 'comment'
                        AND LENGTH(TRIM(COALESCE(r.comment_text, ''))) < 3
                   )
                """
            ).fetchone()["c"]
            dislikes = conn.execute(
                """
                SELECT COUNT(DISTINCT profile_id) AS c
                FROM reactions
                WHERE reaction_type = 'dislike'
                """
            ).fetchone()["c"]
            mutual_likes = conn.execute(
                "SELECT COUNT(*) AS c FROM profiles WHERE mutual_like = 1"
            ).fetchone()["c"]
            comments = conn.execute(
                """
                SELECT COUNT(DISTINCT profile_id) AS c
                FROM reactions r
                WHERE r.reaction_type = 'comment'
                  AND LENGTH(TRIM(COALESCE(r.comment_text, ''))) >= 3
                  AND TRIM(r.comment_text) NOT IN ('❤️', '❤', '👎', '💌', '💌 / 📹')
                """
            ).fetchone()["c"]
        return ProfileStats(
            profiles=profiles,
            likes=likes,
            dislikes=dislikes,
            comments=comments,
            mutual_likes=mutual_likes,
        )
