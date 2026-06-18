"""Извлечение увлечений, вузов, тональности и прочих сигналов из текста анкеты."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from services.signal_catalog import load_catalog, match_catalog_entries


GLUED_MEDIA_RE = re.compile(
    r"сериалы\s*фильмы\s*книги\s*манга|"
    r"сериалы\s*фильмы\s*книги|"
    r"фильмы\s*книги\s*манга|"
    r"сериалы\s*фильмы",
    re.IGNORECASE,
)

HEIGHT_PAREN_RE = re.compile(r"\(\s*рост\s*\d{2,3}\s*\)", re.IGNORECASE)
METRO_RE = re.compile(
    r"(?:м\.|метро|станци[яи])\s*([а-яё\-]+)|"
    r"\b(арбатская|сокол|тульская|киевская|белорусская|комсомольская|"
    r"вднх|марьино|люблино|митино|строгино)\b",
    re.IGNORECASE,
)


@dataclass
class ProfileSignals:
    universities: list[str] = field(default_factory=list)
    university_psychology: bool = False
    artists: list[str] = field(default_factory=list)
    games: list[str] = field(default_factory=list)
    fandoms: list[str] = field(default_factory=list)
    media_tokens: list[str] = field(default_factory=list)
    glued_media: bool = False
    metro: list[str] = field(default_factory=list)
    location: str | None = None
    tone: list[str] = field(default_factory=list)
    height_in_parens: bool = False
    custom_tags: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | None) -> ProfileSignals:
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError):
            return cls()


def split_glued_media(text: str) -> list[str]:
    if not GLUED_MEDIA_RE.search(text):
        return []
    catalog = load_catalog()
    tokens = catalog.get("media_tokens", [])
    found = [token for token in tokens if token.casefold() in text.casefold()]
    if not found and re.search(r"сериал|фильм|книг|манг", text, re.I):
        return ["сериалы", "фильмы", "книги", "манга"]
    return found


def detect_location(text: str) -> str | None:
    catalog = load_catalog()
    markers = catalog.get("location_markers", {})
    clean = text.casefold()
    for key in ("moscow_region", "commute_ok", "moscow_city"):
        for marker in markers.get(key, []):
            if marker.casefold() in clean:
                return key
    return None


def detect_tone(text: str) -> list[str]:
    catalog = load_catalog()
    clean = text.casefold()
    tone_map = catalog.get("tone_markers", {})
    found: list[str] = []
    for tone, patterns in tone_map.items():
        for pattern in patterns:
            if pattern.casefold() in clean:
                found.append(tone)
                break
    return found


def extract_profile_signals(text: str) -> ProfileSignals:
    raw = (text or "").strip()
    clean = raw.casefold()
    signals = ProfileSignals()

    signals.universities = match_catalog_entries("universities", clean)
    catalog = load_catalog()
    for uni_id in signals.universities:
        for entry in catalog.get("universities", []):
            if entry.get("id") == uni_id and entry.get("psychology"):
                if any(
                    field.casefold() in clean
                    for field in entry.get("fields", [])
                ) or "психолог" in clean:
                    signals.university_psychology = True
                break

    signals.artists = match_catalog_entries("artists", clean)
    signals.games = match_catalog_entries("games", clean)
    signals.fandoms = match_catalog_entries("fandoms", clean)

    media = split_glued_media(raw)
    if media:
        signals.glued_media = True
        signals.media_tokens = media
    else:
        signals.media_tokens = [
            token
            for token in catalog.get("media_tokens", [])
            if token.casefold() in clean
        ]

    for match in METRO_RE.finditer(raw):
        station = match.group(1) or match.group(2)
        if station:
            signals.metro.append(station.casefold())

    signals.location = detect_location(raw)
    signals.tone = detect_tone(raw)
    signals.height_in_parens = bool(HEIGHT_PAREN_RE.search(raw))

    if re.search(r"\bжур\b|журфак|журе\b", clean):
        signals.custom_tags.append("journalism")

    if re.search(r"\bфизмат\b", clean):
        signals.custom_tags.append("physmat")

    if re.search(r"\b(?:intj|infp|entp|estp|enfp|infj)\b", clean):
        signals.custom_tags.append("mbti")

    if re.search(r"генshin|genshin|геншин", clean):
        signals.custom_tags.append("genshin_fd")

    return signals


def format_profile_signals(raw: str | None) -> str:
    signals = ProfileSignals.from_json(raw)
    parts: list[str] = []
    if signals.universities:
        parts.append("Вуз: " + ", ".join(signals.universities))
    if signals.university_psychology:
        parts.append("психология")
    if signals.artists:
        parts.append("Музыка: " + ", ".join(signals.artists[:8]))
    if signals.games:
        parts.append("Игры: " + ", ".join(signals.games[:8]))
    if signals.fandoms:
        parts.append("ФД: " + ", ".join(signals.fandoms[:8]))
    if signals.media_tokens:
        parts.append("Медиа: " + ", ".join(signals.media_tokens))
    if signals.glued_media:
        parts.append("склеенное медиа")
    if signals.metro:
        parts.append("Метро: " + ", ".join(signals.metro))
    if signals.location:
        parts.append(f"локация: {signals.location}")
    if signals.tone:
        parts.append("тон: " + ", ".join(signals.tone))
    if signals.height_in_parens:
        parts.append("рост в скобках")
    if signals.custom_tags:
        parts.append("теги: " + ", ".join(signals.custom_tags))
    return " · ".join(parts)
