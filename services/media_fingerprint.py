import hashlib
import re
from pathlib import Path

from pyrogram.types import Message


def extract_media_fingerprints(messages: list[Message]) -> list[str]:
    fingerprints: list[str] = []
    for message in messages:
        fingerprint = _fingerprint_from_message(message)
        if fingerprint:
            fingerprints.append(fingerprint)
    return sorted(fingerprints)


def _fingerprint_from_message(message: Message) -> str | None:
    if message.photo:
        photo = message.photo
        return f"photo:{photo.file_unique_id}:{photo.file_size or 0}"
    if message.video:
        video = message.video
        return f"video:{video.file_unique_id}:{video.file_size or 0}"
    if message.animation:
        animation = message.animation
        return f"animation:{animation.file_unique_id}:{animation.file_size or 0}"
    return None


def fingerprint_file(path: Path) -> str | None:
    if not path.is_file():
        return None

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def build_content_hash(
    *,
    name: str | None,
    age: int | None,
    raw_text: str,
    media_fingerprints: list[str] | None = None,
) -> str:
    from services.leomatch_parser import extract_bio_text, parse_header_line

    header = parse_header_line(raw_text)
    bio = extract_bio_text(raw_text) or ""
    resolved_name = (header.name or name or "").strip().casefold()
    resolved_age = header.age if header.age is not None else age
    media_part = "|".join(sorted(media_fingerprints or []))
    normalized = "|".join(
        [
            resolved_name,
            str(resolved_age if resolved_age is not None else ""),
            re.sub(r"\s+", " ", bio.strip()).casefold(),
            media_part,
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def resolve_stored_media_path(stored_path: str | None, base_dir: Path) -> Path | None:
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
