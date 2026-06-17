from pathlib import Path

from pyrogram.types import Message

from database.repository import ProfileRepository, build_search_text
from services.leomatch_parser import parse_profile_text
from services.media_analysis import PHOTO_TYPES, compress_image_file
from services.media_fingerprint import build_content_hash, extract_media_fingerprints
from services.profile_text_analysis import analyze_profile_text
from services.trash_backfill import run_trash_analysis_for_profile


async def save_profile_from_messages(
    client,
    repo: ProfileRepository,
    messages: list[Message],
    media_dir: Path,
) -> int | None:
    if not messages:
        return None

    anchor = messages[0]
    chat_id = anchor.chat.id
    message_id = anchor.id

    existing_id = repo.get_profile_id_by_message(chat_id, message_id)
    if existing_id is not None:
        return existing_id

    caption_parts = [msg.caption or msg.text or "" for msg in messages]
    raw_text = "\n\n".join(part.strip() for part in caption_parts if part.strip())
    parsed = parse_profile_text(raw_text)
    media_fingerprints = extract_media_fingerprints(messages)
    content_hash = build_content_hash(
        name=parsed.name,
        age=parsed.age,
        raw_text=parsed.raw_text or raw_text,
        media_fingerprints=media_fingerprints,
    )

    duplicate_id = repo.get_profile_id_by_content_hash(content_hash)
    if duplicate_id is not None:
        return duplicate_id

    duplicate_id = repo.find_profile_id_by_identity(
        name=parsed.name,
        age=parsed.age,
        content_hash=content_hash,
    )
    if duplicate_id is not None:
        return duplicate_id

    search_text = build_search_text(
        name=parsed.name,
        age=parsed.age,
        city=parsed.city,
        bio_text=parsed.bio_text,
        hobbies=parsed.hobbies,
        raw_text=parsed.raw_text or raw_text,
        real_age=parsed.real_age,
    )
    analysis = analyze_profile_text(
        age=parsed.age,
        real_age=parsed.real_age,
        raw_text=parsed.raw_text or raw_text,
    )

    profile_id = repo.create_profile(
        message_id=message_id,
        chat_id=chat_id,
        name=parsed.name,
        age=parsed.age,
        real_age=parsed.real_age,
        city=parsed.city,
        bio_text=parsed.bio_text,
        hobbies=parsed.hobbies,
        raw_text=parsed.raw_text or raw_text or "(без текста)",
        content_hash=content_hash,
        search_text=search_text,
        word_count=analysis.word_count,
        min_detected_age=analysis.min_detected_age,
        max_detected_age=analysis.max_detected_age,
        age_values=analysis.age_values,
    )

    profile_media_dir = media_dir / str(profile_id)
    profile_media_dir.mkdir(parents=True, exist_ok=True)

    sort_order = 0
    for msg in messages:
        media_type, file_id, file_unique_id = _extract_media_meta(msg)
        if not media_type:
            continue

        extension = "mp4" if media_type in {"video", "animation"} else "jpg"
        target_path = profile_media_dir / f"{sort_order:02d}_{msg.id}.{extension}"
        local_path = await client.download_media(msg, file_name=str(target_path))
        if media_type in PHOTO_TYPES:
            compress_image_file(Path(local_path))

        stored_path = str(Path(local_path).relative_to(media_dir.parent.parent))

        repo.add_media(
            profile_id=profile_id,
            message_id=msg.id,
            media_type=media_type,
            file_id=file_id,
            file_unique_id=file_unique_id,
            local_path=stored_path,
            sort_order=sort_order,
        )
        sort_order += 1

    run_trash_analysis_for_profile(
        repo,
        profile_id,
        raw_text=parsed.raw_text or raw_text or "(без текста)",
        name=parsed.name,
        age=parsed.age,
        word_count=analysis.word_count,
        base_dir=media_dir.parent.parent,
        compress_photos=False,
    )

    return profile_id


def _extract_media_meta(message: Message) -> tuple[str | None, str | None, str | None]:
    if message.photo:
        return "photo", message.photo.file_id, message.photo.file_unique_id
    if message.video:
        return "video", message.video.file_id, message.video.file_unique_id
    if message.animation:
        return "animation", message.animation.file_id, message.animation.file_unique_id
    return None, None, None
