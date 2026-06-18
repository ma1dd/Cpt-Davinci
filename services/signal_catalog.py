"""Каталог сигналов и настраиваемых правил скоринга."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CATALOG_PATH = BASE_DIR / "data" / "signals_catalog.json"
OVERRIDES_PATH = BASE_DIR / "data" / "scoring_overrides.json"


@dataclass(frozen=True)
class ScoringRule:
    id: str
    label: str
    pattern: str
    delta: float
    heavy: bool = False
    per_match: bool = False
    enabled: bool = True
    tag_only: bool = False
    exclude_if: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> ScoringRule:
        return cls(
            id=str(data["id"]),
            label=str(data["label"]),
            pattern=str(data["pattern"]),
            delta=float(data.get("delta", 0)),
            heavy=bool(data.get("heavy", False)),
            per_match=bool(data.get("per_match", False)),
            enabled=bool(data.get("enabled", True)),
            tag_only=bool(data.get("tag_only", False)),
            exclude_if=data.get("exclude_if"),
        )

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "label": self.label,
            "pattern": self.pattern,
            "delta": self.delta,
            "heavy": self.heavy,
            "per_match": self.per_match,
            "enabled": self.enabled,
        }
        if self.tag_only:
            result["tag_only"] = True
        if self.exclude_if:
            result["exclude_if"] = self.exclude_if
        return result


_catalog_cache: dict | None = None
_overrides_cache: dict | None = None


def load_catalog() -> dict:
    global _catalog_cache
    if _catalog_cache is None:
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            _catalog_cache = json.load(handle)
    return _catalog_cache


def load_overrides() -> dict:
    global _overrides_cache
    if _overrides_cache is None:
        if OVERRIDES_PATH.is_file():
            with OVERRIDES_PATH.open(encoding="utf-8") as handle:
                _overrides_cache = json.load(handle)
        else:
            _overrides_cache = {"version": 1, "rules": {}}
    return _overrides_cache


def save_overrides(overrides: dict) -> None:
    global _overrides_cache
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OVERRIDES_PATH.open("w", encoding="utf-8") as handle:
        json.dump(overrides, handle, ensure_ascii=False, indent=2)
    _overrides_cache = overrides


def reload_catalog() -> None:
    global _catalog_cache, _overrides_cache
    _catalog_cache = None
    _overrides_cache = None


def get_scoring_rules() -> list[ScoringRule]:
    catalog = load_catalog()
    overrides = load_overrides().get("rules", {})
    rules: list[ScoringRule] = []
    for raw in catalog.get("custom_rules", []):
        rule = ScoringRule.from_dict(raw)
        patch = overrides.get(rule.id)
        if patch:
            merged = rule.to_dict()
            merged.update(patch)
            rule = ScoringRule.from_dict(merged)
        rules.append(rule)
    return rules


def update_rule_override(
    rule_id: str,
    *,
    delta: float | None = None,
    enabled: bool | None = None,
    heavy: bool | None = None,
) -> None:
    overrides = deepcopy(load_overrides())
    rules = overrides.setdefault("rules", {})
    entry = dict(rules.get(rule_id, {}))
    if delta is not None:
        entry["delta"] = delta
    if enabled is not None:
        entry["enabled"] = enabled
    if heavy is not None:
        entry["heavy"] = heavy
    rules[rule_id] = entry
    save_overrides(overrides)


def apply_custom_rules(text: str, add) -> list[str]:
    """Применяет правила из каталога. add(delta, label, heavy=...). Возвращает теги-сигналы."""
    clean = (text or "").casefold()
    tags: list[str] = []
    for rule in get_scoring_rules():
        if not rule.enabled:
            continue
        if rule.exclude_if and re.search(rule.exclude_if, clean, re.IGNORECASE):
            continue
        try:
            compiled = re.compile(rule.pattern, re.IGNORECASE | re.DOTALL)
        except re.error:
            continue
        matches = list(compiled.finditer(clean))
        if not matches:
            continue
        tags.append(rule.label)
        if rule.tag_only:
            continue
        count = len(matches) if rule.per_match else 1
        add(rule.delta * count, rule.label, heavy=rule.heavy)
    return tags


def match_catalog_entries(category: str, text: str) -> list[str]:
    catalog = load_catalog()
    clean = text.casefold()
    found: list[str] = []
    for entry in catalog.get(category, []):
        entry_id = entry.get("id", "")
        for name in entry.get("names", []):
            if name.casefold() in clean:
                found.append(entry_id)
                break
    return found
