from pathlib import Path

from database.repository import ProfileRepository
from services.profile_trash_service import analyze_profile_trash
from services.trash_analyzer import TRASH_ANALYSIS_VERSION


def run_trash_analysis_for_profile(
    repo: ProfileRepository,
    profile_id: int,
    *,
    raw_text: str,
    name: str | None,
    age: int | None,
    word_count: int | None,
    base_dir: Path,
    compress_photos: bool = False,
) -> None:
    media_rows = repo.get_profile_media_rows(profile_id)
    result, media_items = analyze_profile_trash(
        raw_text=raw_text,
        name=name,
        age=age,
        word_count=word_count,
        media_rows=[(m[0], m[1]) for m in media_rows],
        base_dir=base_dir,
        compress_photos=compress_photos,
    )
    repo.update_profile_trash(
        profile_id,
        trash_score=result.score,
        trash_label=result.label,
        trash_tags=result.tags_json(),
        trash_analysis_version=TRASH_ANALYSIS_VERSION,
    )
    for index, item in enumerate(media_items):
        if index < len(media_rows):
            sort_order = media_rows[index][2]
            repo.set_media_face_count(profile_id, sort_order, item.face_count)
