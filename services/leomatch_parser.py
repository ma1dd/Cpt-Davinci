import re
from dataclasses import dataclass

MOSCOW_ALIASES = frozenset({"москва", "мск", "moscow"})
FILTER_CITY_OPTIONS = ["Москва"]


@dataclass
class ParsedProfile:
    name: str | None
    age: int | None
    real_age: int | None
    city: str | None
    bio_text: str | None
    hobbies: str | None
    raw_text: str


@dataclass
class HeaderFields:
    name: str | None
    age: int | None
    city: str | None
    bio: str | None


def parse_header_line(raw_text: str | None) -> HeaderFields:
    raw = (raw_text or "").strip()
    if not raw:
        return HeaderFields(None, None, None, None)

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    first_line = lines[0]
    header_segment = re.split(r"\s*[–—-]\s*", first_line, maxsplit=1)[0].strip()
    parts = [part.strip() for part in header_segment.split(",")]

    name = parts[0] if parts else None
    age = None
    city = None

    if len(parts) >= 2:
        age_match = re.search(r"\d{1,2}", parts[1])
        if age_match:
            age = int(age_match.group(0))

    if len(parts) >= 3:
        city_part = parts[2]
        city = format_city_display(re.split(r"\s*[–—-]\s*", city_part)[0].strip())

    bio = extract_bio_text(raw)
    return HeaderFields(name=name, age=age, city=city, bio=bio)


def _is_header_only_segment(segment: str) -> bool:
    parts = [part.strip() for part in segment.split(",")]
    if len(parts) != 3:
        return False
    if not re.fullmatch(r"\d{1,2}", parts[1]):
        return False
    if len(parts[0]) > 40 or len(parts[2]) > 40:
        return False
    return True


def extract_bio_text(raw_text: str | None) -> str | None:
    raw = (raw_text or "").strip()
    if not raw:
        return None

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    bio_lines: list[str] = []

    for index, line in enumerate(lines):
        segments = re.split(r"\s*[–—-]\s*", line)
        kept: list[str] = []
        for segment in segments:
            segment = segment.strip()
            if not segment:
                continue
            if index == 0 and _is_header_only_segment(segment):
                continue
            kept.append(segment)
        if kept:
            bio_lines.append(" – ".join(kept))

    bio = "\n".join(bio_lines).strip()
    return bio or None


def _city_token(value: str) -> str:
    return re.split(r"[\s,]", value.strip(), maxsplit=1)[0].casefold()


def format_city_display(city: str | None) -> str | None:
    if not city:
        return None
    value = city.strip()
    if not value:
        return None
    if _city_token(value) in MOSCOW_ALIASES:
        return "Москва"
    return value


def display_city(city: str | None = None, raw_text: str | None = None) -> str:
    header = parse_header_line(raw_text)
    if header.city:
        return header.city
    formatted = format_city_display(city)
    return formatted or "—"


def profile_matches_moscow(*, city: str | None, raw_text: str | None) -> bool:
    header = parse_header_line(raw_text)
    tokens = {
        (header.city or "").casefold(),
        (city or "").casefold(),
        (raw_text or "").casefold(),
    }
    if header.city and header.city.casefold() in MOSCOW_ALIASES:
        return True
    haystack = " ".join(token for token in tokens if token)
    return any(alias in haystack for alias in MOSCOW_ALIASES)


def parse_profile_text(text: str | None) -> ParsedProfile:
    raw = (text or "").strip()
    if not raw:
        return ParsedProfile(None, None, None, None, None, None, "")

    header = parse_header_line(raw)
    real_age = None
    real_age_match = re.search(
        r"настоящ(?:ий|ая)\s+возраст[^\d]{0,10}(\d{1,2})",
        raw,
        re.IGNORECASE,
    )
    if real_age_match:
        real_age = int(real_age_match.group(1))

    return ParsedProfile(
        name=header.name,
        age=header.age,
        real_age=real_age,
        city=header.city,
        bio_text=header.bio,
        hobbies=None,
        raw_text=raw,
    )
