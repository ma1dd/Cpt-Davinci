import re

from services.leomatch_parser import extract_bio_text, parse_header_line
from services.media_fingerprint import build_content_hash


def is_mutual_match_message(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.casefold()
    if "t.me/" not in lowered and "начинай общаться" not in lowered:
        return False
    return any(
        marker in lowered
        for marker in (
            "отлично",
            "надеюсь",
            "взаимн",
            "совпаден",
            "начинай общаться",
        )
    )


def looks_like_profile_text(text: str | None) -> bool:
    header = parse_header_line(text)
    return bool(header.name and header.age is not None)


def build_identity_hash_from_text(text: str) -> str:
    header = parse_header_line(text)
    return build_content_hash(
        name=header.name,
        age=header.age,
        raw_text=text,
        media_fingerprints=[],
    )


def profile_identity_matches(raw_text: str, *, name: str | None, age: int | None) -> bool:
    header = parse_header_line(raw_text)
    if not header.name or header.age is None:
        return False
    if name and header.name.casefold() != name.casefold():
        return False
    if age is not None and header.age != age:
        return False
    return True


def bio_snippet(text: str, limit: int = 80) -> str:
    bio = extract_bio_text(text) or ""
    bio = re.sub(r"\s+", " ", bio).strip()
    if len(bio) <= limit:
        return bio
    return bio[: limit - 1] + "…"
