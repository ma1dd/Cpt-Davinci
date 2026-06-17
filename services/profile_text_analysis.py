"""Анализ текста анкет: заявленный возраст, количество слов и т.д."""
from __future__ import annotations

import re
from dataclasses import dataclass

from services.leomatch_parser import extract_bio_text

# «мне 16», «мне21», «Мне, 21»
_CLAIMED_AGE_PATTERN = re.compile(r"\bмне\s*(\d{1,2})\b", re.IGNORECASE)

_MIN_AGE = 10
_MAX_AGE = 99


@dataclass(frozen=True)
class ProfileTextAnalysis:
    word_count: int
    claimed_ages: tuple[int, ...]
    min_detected_age: int | None
    max_detected_age: int | None
    age_values: str | None


def extract_claimed_ages(text: str | None) -> list[int]:
    raw = (text or "").strip()
    if not raw:
        return []

    found: list[int] = []
    for match in _CLAIMED_AGE_PATTERN.finditer(raw):
        age = int(match.group(1))
        if _MIN_AGE <= age <= _MAX_AGE:
            found.append(age)

    return sorted(set(found))


def count_profile_words(raw_text: str | None) -> int:
    bio = extract_bio_text(raw_text)
    if not bio:
        return 0
    return len(re.findall(r"\S+", bio))


def collect_detected_ages(
    *,
    age: int | None,
    real_age: int | None,
    raw_text: str | None,
) -> tuple[tuple[int, ...], int | None, int | None]:
    values: set[int] = set()
    if age is not None and _MIN_AGE <= age <= _MAX_AGE:
        values.add(age)
    if real_age is not None and _MIN_AGE <= real_age <= _MAX_AGE:
        values.add(real_age)
    values.update(extract_claimed_ages(raw_text))

    if not values:
        return (), None, None

    ordered = tuple(sorted(values))
    return ordered, min(values), max(values)


def analyze_profile_text(
    *,
    age: int | None,
    real_age: int | None,
    raw_text: str | None,
) -> ProfileTextAnalysis:
    word_count = count_profile_words(raw_text)
    claimed_ages = tuple(extract_claimed_ages(raw_text))
    ages, min_age, max_age = collect_detected_ages(
        age=age,
        real_age=real_age,
        raw_text=raw_text,
    )
    age_values = ",".join(str(value) for value in ages) if ages else None
    return ProfileTextAnalysis(
        word_count=word_count,
        claimed_ages=claimed_ages,
        min_detected_age=min_age,
        max_detected_age=max_age,
        age_values=age_values,
    )


def extra_search_tokens(analysis: ProfileTextAnalysis) -> str:
    parts = [str(age) for age in analysis.claimed_ages]
    for age in analysis.claimed_ages:
        parts.append(f"мне {age}")
        parts.append(f"мне{age}")
    return " ".join(parts)
