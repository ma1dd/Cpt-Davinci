import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from services.leomatch_parser import (
    FILTER_CITY_OPTIONS,
    display_city,
    extract_bio_text,
    parse_header_line,
)
from services.profile_text_analysis import analyze_profile_text, extra_search_tokens
from services.trash_analyzer import TRASH_ANALYSIS_VERSION, TrashAnalysisResult, TrashTag

_ANALYSIS_VERSION = 1
_BACKFILL_TRASH_BATCH = 15


class ReactionFilter(str, Enum):
    ALL = "all"
    LIKE = "like"
    DISLIKE = "dislike"
    COMMENT = "comment"
    MUTUAL = "mutual"


_TEXT_COMMENT_SQL = """
    r.reaction_type = 'comment'
    AND LENGTH(TRIM(COALESCE(r.comment_text, ''))) >= 3
    AND TRIM(r.comment_text) NOT IN ('❤️', '❤', '👎', '💌', '💌 / 📹')
"""

_LIKE_REACTION_SQL = """
    (
        r.reaction_type = 'like'
        OR r.reaction_type = 'comment'
    )
"""


class PeriodFilter(str, Enum):
    ALL = "all"
    TODAY = "today"
    WEEK = "week"


@dataclass
class FilterParams:
    keyword: str = ""
    city: str = ""
    age_from: int = 18
    age_to: int = 99
    min_words: int = 0
    reaction: ReactionFilter = ReactionFilter.ALL
    period: PeriodFilter = PeriodFilter.ALL


@dataclass
class ReactionInfo:
    reaction_type: str
    comment_text: str | None


@dataclass
class MediaInfo:
    media_type: str
    local_path: str | None
    sort_order: int


@dataclass
class ProfileSummary:
    id: int
    name: str | None
    age: int | None
    city: str | None
    raw_text: str
    created_at: str
    reaction_label: str
    trash_score: float | None = None
    trash_label: str | None = None


@dataclass
class ViewerStats:
    profiles: int
    likes: int
    dislikes: int
    comments: int
    mutual_likes: int
    avg_trash_score: float | None
    trash_over_90_pct: float | None


@dataclass
class ProfileView:
    id: int
    name: str | None
    age: int | None
    real_age: int | None
    city: str | None
    bio_text: str | None
    hobbies: str | None
    raw_text: str
    created_at: str
    mutual_like: bool = False
    trash_score: float | None = None
    trash_label: str | None = None
    trash_tags: list[TrashTag] = field(default_factory=list)
    detected_signals: str | None = None
    media: list[MediaInfo] = field(default_factory=list)
    reactions: list[ReactionInfo] = field(default_factory=list)


class ProfileViewerRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.base_dir = db_path.resolve().parent.parent

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_search_columns(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(profiles)").fetchall()
        }
        if "search_text" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN search_text TEXT")
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

        rows = conn.execute(
            """
            SELECT id, name, age, real_age, city, bio_text, hobbies, raw_text
            FROM profiles
            WHERE COALESCE(analysis_version, 0) < ?
            """,
            (_ANALYSIS_VERSION,),
        ).fetchall()
        for row in rows:
            analysis = analyze_profile_text(
                age=row["age"],
                real_age=row["real_age"],
                raw_text=row["raw_text"],
            )
            search_text = " ".join(
                part.strip()
                for part in (
                    row["name"],
                    row["city"],
                    row["bio_text"],
                    row["hobbies"],
                    row["raw_text"],
                    str(row["age"]) if row["age"] is not None else "",
                    str(row["real_age"]) if row["real_age"] is not None else "",
                    extra_search_tokens(analysis),
                )
                if part and str(part).strip()
            ).casefold()
            conn.execute(
                """
                UPDATE profiles
                SET search_text = ?,
                    word_count = ?,
                    min_detected_age = ?,
                    max_detected_age = ?,
                    age_values = ?,
                    analysis_version = ?
                WHERE id = ?
                """,
                (
                    search_text,
                    analysis.word_count,
                    analysis.min_detected_age,
                    analysis.max_detected_age,
                    analysis.age_values,
                    _ANALYSIS_VERSION,
                    row["id"],
                ),
            )

    def _ensure_profile_columns(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(profiles)").fetchall()
        }
        if "mutual_like" not in columns:
            conn.execute(
                "ALTER TABLE profiles ADD COLUMN mutual_like INTEGER NOT NULL DEFAULT 0"
            )

    def _ensure_trash_columns(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(profiles)").fetchall()
        }
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
        if "face_count" not in media_columns:
            conn.execute("ALTER TABLE profile_media ADD COLUMN face_count INTEGER")

    def count_pending_trash_analysis(self) -> int:
        with self._connect() as conn:
            self._ensure_trash_columns(conn)
            row = conn.execute(
                """
                SELECT COUNT(*) AS c FROM profiles
                WHERE COALESCE(trash_analysis_version, 0) < ?
                """,
                (TRASH_ANALYSIS_VERSION,),
            ).fetchone()
        return int(row["c"])

    def backfill_trash_analysis(self, *, limit: int = _BACKFILL_TRASH_BATCH) -> int:
        from database.repository import ProfileRepository
        from services.trash_backfill import run_trash_analysis_for_profile

        with self._connect() as conn:
            self._ensure_trash_columns(conn)
            rows = conn.execute(
                """
                SELECT id, raw_text, name, age, word_count
                FROM profiles
                WHERE COALESCE(trash_analysis_version, 0) < ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (TRASH_ANALYSIS_VERSION, limit),
            ).fetchall()

        if not rows:
            return 0

        write_repo = ProfileRepository(self.db_path, self.base_dir)
        for row in rows:
            run_trash_analysis_for_profile(
                write_repo,
                int(row["id"]),
                raw_text=row["raw_text"],
                name=row["name"],
                age=row["age"],
                word_count=row["word_count"],
                base_dir=self.base_dir,
                compress_photos=False,
            )
        return len(rows)

    def get_latest_profiles(self, limit: int = 10) -> list[ProfileSummary]:
        with self._connect() as conn:
            self._ensure_search_columns(conn)
            self._ensure_profile_columns(conn)
            self._ensure_trash_columns(conn)
            rows = conn.execute(
                """
                SELECT
                    p.id,
                    p.name,
                    p.age,
                    p.city,
                    p.raw_text,
                    p.created_at,
                    p.mutual_like,
                    p.trash_score,
                    p.trash_label,
                    GROUP_CONCAT(r.reaction_type, ',') AS reaction_types
                FROM profiles p
                LEFT JOIN reactions r ON r.profile_id = p.id
                GROUP BY p.id
                ORDER BY p.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            ProfileSummary(
                id=int(row["id"]),
                name=row["name"],
                age=row["age"],
                city=row["city"],
                raw_text=row["raw_text"],
                created_at=row["created_at"],
                reaction_label=_summarize_reactions(
                    row["reaction_types"],
                    mutual=bool(row["mutual_like"]),
                ),
                trash_score=row["trash_score"],
                trash_label=row["trash_label"],
            )
            for row in rows
        ]

    def get_cities(self) -> list[str]:
        return list(FILTER_CITY_OPTIONS)

    def get_stats(self) -> ViewerStats:
        with self._connect() as conn:
            self._ensure_profile_columns(conn)
            self._ensure_trash_columns(conn)
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
            comments = conn.execute(
                f"""
                SELECT COUNT(DISTINCT profile_id) AS c
                FROM reactions r
                WHERE {_TEXT_COMMENT_SQL.strip()}
                """
            ).fetchone()["c"]
            mutual_likes = conn.execute(
                "SELECT COUNT(*) AS c FROM profiles WHERE mutual_like = 1"
            ).fetchone()["c"]
            avg_row = conn.execute(
                """
                SELECT AVG(trash_score) AS avg_trash
                FROM profiles
                WHERE trash_score IS NOT NULL
                """
            ).fetchone()
            avg_trash = avg_row["avg_trash"]
            over90_row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN trash_score > 90 THEN 1 ELSE 0 END) AS over90,
                    COUNT(*) AS total
                FROM profiles
                WHERE trash_score IS NOT NULL
                """
            ).fetchone()
            over90 = int(over90_row["over90"] or 0)
            scored_total = int(over90_row["total"] or 0)
            trash_over_90_pct = (
                100.0 * over90 / scored_total if scored_total > 0 else None
            )
        return ViewerStats(
            profiles=profiles,
            likes=likes,
            dislikes=dislikes,
            comments=comments,
            mutual_likes=mutual_likes,
            avg_trash_score=float(avg_trash) if avg_trash is not None else None,
            trash_over_90_pct=trash_over_90_pct,
        )

    def search_profile_summaries(self, filters: FilterParams) -> list[ProfileSummary]:
        ids = self.search_profiles(filters)
        if not ids:
            return []

        placeholders = ",".join("?" for _ in ids)
        query = f"""
            SELECT
                p.id,
                p.name,
                p.age,
                p.city,
                p.raw_text,
                p.created_at,
                p.mutual_like,
                p.trash_score,
                p.trash_label,
                GROUP_CONCAT(r.reaction_type, ',') AS reaction_types
            FROM profiles p
            LEFT JOIN reactions r ON r.profile_id = p.id
            WHERE p.id IN ({placeholders})
            GROUP BY p.id
            ORDER BY p.id DESC
        """
        with self._connect() as conn:
            rows = conn.execute(query, ids).fetchall()

        summaries: list[ProfileSummary] = []
        for row in rows:
            summaries.append(
                ProfileSummary(
                    id=int(row["id"]),
                    name=row["name"],
                    age=row["age"],
                    city=row["city"],
                    raw_text=row["raw_text"],
                    created_at=row["created_at"],
                    reaction_label=_summarize_reactions(
                    row["reaction_types"],
                    mutual=bool(row["mutual_like"]),
                ),
                    trash_score=row["trash_score"],
                    trash_label=row["trash_label"],
                )
            )
        return summaries

    def search_profiles(self, filters: FilterParams) -> list[int]:
        conditions = ["1=1"]
        params: list[object] = []

        keyword = filters.keyword.strip().casefold()
        if keyword:
            conditions.append("COALESCE(p.search_text, '') LIKE ?")
            params.append(f"%{keyword}%")

        city = filters.city.strip()
        if city == "Москва":
            conditions.append(
                """
                (
                    COALESCE(p.search_text, '') LIKE '%москва%'
                    OR COALESCE(p.search_text, '') LIKE '%мск%'
                )
                """
            )
        elif city and city != "— любой —":
            needle = f"%{city.casefold()}%"
            conditions.append("COALESCE(p.search_text, '') LIKE ?")
            params.append(needle)

        conditions.append(
            """
            (
                p.min_detected_age IS NOT NULL
                AND p.max_detected_age IS NOT NULL
                AND p.min_detected_age <= ?
                AND p.max_detected_age >= ?
            )
            """
        )
        params.extend([filters.age_to, filters.age_from])

        if filters.min_words > 0:
            conditions.append("COALESCE(p.word_count, 0) > ?")
            params.append(filters.min_words)

        if filters.reaction == ReactionFilter.LIKE:
            conditions.append(
                f"""
                EXISTS (
                    SELECT 1 FROM reactions r
                    WHERE r.profile_id = p.id
                      AND {_LIKE_REACTION_SQL.strip()}
                )
                """
            )
        elif filters.reaction == ReactionFilter.DISLIKE:
            conditions.append(
                """
                EXISTS (
                    SELECT 1 FROM reactions r
                    WHERE r.profile_id = p.id AND r.reaction_type = 'dislike'
                )
                """
            )
        elif filters.reaction == ReactionFilter.COMMENT:
            conditions.append(
                f"""
                EXISTS (
                    SELECT 1 FROM reactions r
                    WHERE r.profile_id = p.id
                      AND {_TEXT_COMMENT_SQL.strip()}
                )
                """
            )
        elif filters.reaction == ReactionFilter.MUTUAL:
            conditions.append("COALESCE(p.mutual_like, 0) = 1")

        if filters.period == PeriodFilter.TODAY:
            conditions.append("DATE(p.created_at) = DATE('now', 'localtime')")
        elif filters.period == PeriodFilter.WEEK:
            conditions.append(
                "p.created_at >= DATETIME('now', 'localtime', '-7 days')"
            )

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT p.id
            FROM profiles p
            WHERE {where_clause}
            ORDER BY p.id DESC
        """

        with self._connect() as conn:
            self._ensure_search_columns(conn)
            self._ensure_profile_columns(conn)
            self._ensure_trash_columns(conn)
            rows = conn.execute(query, params).fetchall()
        return [int(row["id"]) for row in rows]

    def get_profile(self, profile_id: int) -> ProfileView | None:
        with self._connect() as conn:
            self._ensure_profile_columns(conn)
            self._ensure_trash_columns(conn)
            profile = conn.execute(
                """
                SELECT id, name, age, real_age, city, bio_text, hobbies, raw_text,
                       created_at, mutual_like, trash_score, trash_label, trash_tags,
                       detected_signals
                FROM profiles
                WHERE id = ?
                """,
                (profile_id,),
            ).fetchone()
            if profile is None:
                return None

            media_rows = conn.execute(
                """
                SELECT media_type, local_path, sort_order
                FROM profile_media
                WHERE profile_id = ?
                ORDER BY sort_order, id
                """,
                (profile_id,),
            ).fetchall()

            reaction_rows = conn.execute(
                """
                SELECT reaction_type, comment_text
                FROM reactions
                WHERE profile_id = ?
                ORDER BY created_at, id
                """,
                (profile_id,),
            ).fetchall()

        trash_result = TrashAnalysisResult.from_json(
            profile["trash_score"],
            profile["trash_label"],
            profile["trash_tags"],
        )
        return ProfileView(
            id=int(profile["id"]),
            name=profile["name"],
            age=profile["age"],
            real_age=profile["real_age"],
            city=profile["city"],
            bio_text=profile["bio_text"],
            hobbies=profile["hobbies"],
            raw_text=profile["raw_text"],
            created_at=profile["created_at"],
            mutual_like=bool(profile["mutual_like"]),
            trash_score=profile["trash_score"],
            trash_label=profile["trash_label"],
            trash_tags=trash_result.tags,
            detected_signals=profile["detected_signals"],
            media=[
                MediaInfo(
                    media_type=row["media_type"],
                    local_path=row["local_path"],
                    sort_order=row["sort_order"],
                )
                for row in media_rows
            ],
            reactions=[
                ReactionInfo(
                    reaction_type=row["reaction_type"],
                    comment_text=row["comment_text"],
                )
                for row in reaction_rows
            ],
        )


def _summarize_reactions(raw: str | None, *, mutual: bool = False) -> str:
    labels: list[str] = []
    if mutual:
        labels.append("💞")
    if not raw:
        return " ".join(labels) if labels else "—"
    types = {part.strip() for part in raw.split(",") if part.strip()}
    if "like" in types:
        labels.append("❤️")
    if "dislike" in types:
        labels.append("👎")
    if "comment" in types:
        labels.append("💬")
    return " ".join(labels) if labels else "—"


def resolve_media_path(stored_path: str | None, base_dir: Path) -> Path | None:
    if not stored_path:
        return None

    candidate = Path(stored_path)
    options = [
        candidate,
        base_dir / stored_path,
        base_dir / stored_path.replace("\\", "/"),
    ]

    if candidate.is_absolute():
        parts = candidate.parts
        if "data" in parts:
            data_index = parts.index("data")
            options.append(base_dir / Path(*parts[data_index:]))

    for path in options:
        if path.is_file():
            return path
    return None


_EMOJI_ONLY = frozenset({"❤️", "❤", "👎", "💌", "💌 / 📹"})


def collect_reaction_messages(reactions: list[ReactionInfo]) -> list[str]:
    messages: list[str] = []
    for reaction in reactions:
        text = (reaction.comment_text or "").strip()
        if reaction.reaction_type == "comment":
            if len(text) >= 3 and text not in _EMOJI_ONLY:
                messages.append(text)
            continue
        if text and text not in _EMOJI_ONLY and len(text) >= 3:
            messages.append(text)
    return messages


def reaction_kind(profile: ProfileView) -> str | None:
    """none | like | dislike | mutual | message"""
    if profile.mutual_like:
        return "mutual"
    if not profile.reactions:
        return None

    messages = collect_reaction_messages(profile.reactions)
    if messages:
        return "message"

    last = profile.reactions[-1]
    if last.reaction_type == "like":
        return "like"
    if last.reaction_type == "dislike":
        return "dislike"

    text = (last.comment_text or "").strip()
    if text in {"❤️", "❤"}:
        return "like"
    if text == "👎":
        return "dislike"
    if last.reaction_type == "comment" and len(text) >= 3:
        return "message"
    return None


def format_reaction_messages(profile: ProfileView) -> str:
    messages = collect_reaction_messages(profile.reactions)
    if not messages:
        return ""
    return "\n".join(messages)


def build_description(profile: ProfileView) -> str:
    bio = extract_bio_text(profile.raw_text)
    if bio:
        return bio

    raw = (profile.raw_text or "").strip()
    if not raw:
        return "Описание отсутствует"

    return "Описание отсутствует"


def build_profile_title(
    *,
    name: str | None,
    age: int | None,
    city: str | None,
    raw_text: str | None,
) -> str:
    header = parse_header_line(raw_text)
    resolved_name = header.name or name or "Без имени"
    resolved_age = header.age if header.age is not None else age
    resolved_city = header.city or display_city(city, raw_text)
    age_text = resolved_age if resolved_age is not None else "?"
    return f"{resolved_name}, {age_text}, {resolved_city}"


def build_title(profile: ProfileView) -> str:
    return build_profile_title(
        name=profile.name,
        age=profile.age,
        city=profile.city,
        raw_text=profile.raw_text,
    )


def build_summary_title(summary: ProfileSummary) -> str:
    return build_profile_title(
        name=summary.name,
        age=summary.age,
        city=summary.city,
        raw_text=summary.raw_text,
    )
