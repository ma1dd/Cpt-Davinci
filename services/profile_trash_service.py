"""Полный анализ мусорности профиля (текст + медиа)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from database.viewer_queries import resolve_media_path
from services.media_analysis import (
    PHOTO_TYPES,
    VIDEO_TYPES,
    PhotoAnalysis,
    analyze_media_file,
    compress_image_file,
)
from services.trash_analyzer import TrashAnalysisResult, analyze_trash


@dataclass(frozen=True)
class MediaAnalysisItem:
    media_type: str
    local_path: str | None
    face_count: int
    is_bw: bool = False
    has_phone: bool = False


def analyze_media_items(
    media_rows: list[tuple[str, str | None]],
    base_dir: Path,
    *,
    compress_photos: bool = False,
) -> list[MediaAnalysisItem]:
    results: list[MediaAnalysisItem] = []
    for media_type, stored_path in media_rows:
        resolved = resolve_media_path(stored_path, base_dir)
        analysis = PhotoAnalysis(face_count=0, is_bw=False, has_phone=False)
        if resolved and resolved.is_file():
            if compress_photos and media_type in PHOTO_TYPES:
                compress_image_file(resolved)
            analysis = analyze_media_file(resolved, media_type)
        results.append(
            MediaAnalysisItem(
                media_type=media_type,
                local_path=stored_path,
                face_count=analysis.face_count,
                is_bw=analysis.is_bw,
                has_phone=analysis.has_phone,
            )
        )
    return results


def analyze_profile_trash(
    *,
    raw_text: str,
    name: str | None,
    age: int | None,
    word_count: int | None,
    media_rows: list[tuple[str, str | None]],
    base_dir: Path,
    compress_photos: bool = False,
) -> tuple[TrashAnalysisResult, list[MediaAnalysisItem], "ProfileSignals"]:
    media = analyze_media_items(
        media_rows,
        base_dir,
        compress_photos=compress_photos,
    )
    photos = [m for m in media if m.media_type in PHOTO_TYPES]
    photo_faces = [m.face_count for m in photos]
    photo_bw = [m.is_bw for m in photos]
    photo_phone = [m.has_phone for m in photos]
    photo_count = len(photos)
    has_video = any(m.media_type in VIDEO_TYPES for m in media)

    result = analyze_trash(
        raw_text=raw_text,
        nickname=name or "",
        photo_face_counts=photo_faces,
        photo_bw_flags=photo_bw,
        photo_phone_flags=photo_phone,
        photo_count=photo_count,
        has_video=has_video,
        profile_age=age,
        word_count=word_count,
    )
    from services.signal_extractor import extract_profile_signals

    signals = extract_profile_signals(raw_text)
    return result, media, signals
