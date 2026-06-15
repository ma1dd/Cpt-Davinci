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


@dataclass
class ViewerStats:
    profiles: int
    likes: int
    dislikes: int
    comments: int
    mutual_likes: int
    with_media: int
    with_reaction: int


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
    media: list[MediaInfo] = field(default_factory=list)
    reactions: list[ReactionInfo] = field(default_factory=list)


class ProfileViewerRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

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
        rows = conn.execute(
            "SELECT id, name, age, city, bio_text, hobbies, raw_text, search_text FROM profiles"
        ).fetchall()
        for row in rows:
            if row["search_text"]:
                continue
            search_text = " ".join(
                part.strip()
                for part in (
                    row["name"],
                    row["city"],
                    row["bio_text"],
                    row["hobbies"],
                    row["raw_text"],
                    str(row["age"]) if row["age"] is not None else "",
                )
                if part and str(part).strip()
            ).casefold()
            conn.execute(
                "UPDATE profiles SET search_text = ? WHERE id = ?",
                (search_text, row["id"]),
            )

    def _ensure_profile_columns(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(profiles)").fetchall()
        }
        if "mutual_like" not in columns:
            conn.execute(
                "ALTER TABLE profiles ADD COLUMN mutual_like INTEGER NOT NULL DEFAULT 0"
            )

    def get_latest_profiles(self, limit: int = 10) -> list[ProfileSummary]:
        with self._connect() as conn:
            self._ensure_search_columns(conn)
            self._ensure_profile_columns(conn)
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
            )
            for row in rows
        ]

    def get_cities(self) -> list[str]:
        return list(FILTER_CITY_OPTIONS)

    def get_stats(self) -> ViewerStats:
        with self._connect() as conn:
            self._ensure_profile_columns(conn)
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
            with_media = conn.execute(
                """
                SELECT COUNT(DISTINCT profile_id) AS c
                FROM profile_media
                """
            ).fetchone()["c"]
            with_reaction = conn.execute(
                """
                SELECT COUNT(DISTINCT profile_id) AS c
                FROM reactions
                """
            ).fetchone()["c"]
        return ViewerStats(
            profiles=profiles,
            likes=likes,
            dislikes=dislikes,
            comments=comments,
            mutual_likes=mutual_likes,
            with_media=with_media,
            with_reaction=with_reaction,
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

        conditions.append("(p.age IS NOT NULL AND p.age BETWEEN ? AND ?)")
        params.extend([filters.age_from, filters.age_to])

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
            rows = conn.execute(query, params).fetchall()
        return [int(row["id"]) for row in rows]

    def get_profile(self, profile_id: int) -> ProfileView | None:
        with self._connect() as conn:
            self._ensure_profile_columns(conn)
            profile = conn.execute(
                """
                SELECT id, name, age, real_age, city, bio_text, hobbies, raw_text,
                       created_at, mutual_like
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
        labels.append("❤")
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


def format_reaction_status(profile: ProfileView) -> str:
    if profile.mutual_like:
        return "Взаимный лайк 💞"

    if not profile.reactions:
        return "Нет сохранённой реакции."

    lines: list[str] = []
    for index, reaction in enumerate(profile.reactions, start=1):
        text = (reaction.comment_text or "").strip()
        if text in {"❤️", "❤", "👎"}:
            continue
        if text:
            lines.append(f"{index}. {text}")
        elif reaction.reaction_type == "like":
            lines.append(f"{index}. Лайк")
        elif reaction.reaction_type == "dislike":
            lines.append(f"{index}. Дизлайк")

    if lines:
        return "\n".join(lines)

    primary = profile.reactions[-1]
    if primary.reaction_type == "like":
        return "Лайк"
    if primary.reaction_type == "dislike":
        return "Дизлайк"
    return "Реакция сохранена"


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
