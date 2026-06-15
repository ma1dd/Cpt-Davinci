import sqlite3
from dataclasses import dataclass
from pathlib import Path

from services.media_fingerprint import (
    build_content_hash,
    fingerprint_file,
    resolve_stored_media_path,
)


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
) -> str:
    parts = [name, city, bio_text, hobbies, raw_text, str(age) if age is not None else ""]
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

        media_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(profile_media)").fetchall()
        }
        if "file_unique_id" not in media_columns:
            conn.execute("ALTER TABLE profile_media ADD COLUMN file_unique_id TEXT")

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
            SELECT id, name, age, city, bio_text, hobbies, raw_text, search_text
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
            search_text = row["search_text"] or build_search_text(
                name=row["name"],
                age=row["age"],
                city=row["city"],
                bio_text=row["bio_text"],
                hobbies=row["hobbies"],
                raw_text=row["raw_text"],
            )
            conn.execute(
                """
                UPDATE profiles
                SET content_hash = ?, search_text = ?
                WHERE id = ?
                """,
                (content_hash, search_text, row["id"]),
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
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO profiles (
                    message_id, chat_id, name, age, real_age,
                    city, bio_text, hobbies, raw_text, content_hash, search_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
