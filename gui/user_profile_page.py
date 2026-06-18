"""Страница «Мой профиль» — черновик своей анкеты и превью анализа."""
from __future__ import annotations

import json
from pathlib import Path

import customtkinter as ctk

from gui.emoji_text import plain_ui_font, populate_trash_summary_colored, populate_trash_tag_panels
from services.profile_trash_service import analyze_profile_trash
from services.trash_analyzer import format_trash_percent

USER_PROFILE_PATH = Path(__file__).resolve().parent.parent / "data" / "user_profile.json"


def load_user_profile() -> dict:
    if not USER_PROFILE_PATH.is_file():
        return {"name": "", "age": "18", "city": "Москва", "bio": ""}
    with USER_PROFILE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_user_profile(data: dict) -> None:
    USER_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with USER_PROFILE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


class UserProfilePage(ctk.CTkFrame):
    def __init__(self, master, *, base_dir: Path, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.base_dir = base_dir
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        form.grid_columnconfigure(1, weight=1)

        data = load_user_profile()
        ctk.CTkLabel(form, text="Имя").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.name_entry = ctk.CTkEntry(form)
        self.name_entry.insert(0, data.get("name", ""))
        self.name_entry.grid(row=0, column=1, sticky="ew", pady=2)

        ctk.CTkLabel(form, text="Возраст").grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.age_entry = ctk.CTkEntry(form, width=80)
        self.age_entry.insert(0, str(data.get("age", "18")))
        self.age_entry.grid(row=1, column=1, sticky="w", pady=2)

        ctk.CTkLabel(form, text="Город").grid(row=2, column=0, sticky="w", padx=(0, 8))
        self.city_entry = ctk.CTkEntry(form)
        self.city_entry.insert(0, data.get("city", "Москва"))
        self.city_entry.grid(row=2, column=1, sticky="ew", pady=2)

        ctk.CTkLabel(self, text="Описание", anchor="w").grid(row=1, column=0, sticky="w")
        self.bio_box = ctk.CTkTextbox(self, height=160, font=plain_ui_font(14))
        self.bio_box.grid(row=2, column=0, sticky="nsew", pady=(4, 8))
        self.bio_box.insert("1.0", data.get("bio", ""))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkButton(actions, text="Сохранить", command=self._save).pack(side="left", padx=(0, 8))
        ctk.CTkButton(actions, text="Проверить мусорность", command=self._analyze).pack(side="left")

        self.result_summary = ctk.CTkTextbox(self, height=36, font=plain_ui_font(14))
        self.result_summary.grid(row=4, column=0, sticky="ew", pady=(0, 4))

        tags_row = ctk.CTkFrame(self, fg_color="transparent")
        tags_row.grid(row=5, column=0, sticky="nsew")
        tags_row.grid_columnconfigure((0, 1), weight=1)
        tags_row.grid_rowconfigure(0, weight=1)

        self.minus_box = ctk.CTkTextbox(tags_row, height=120, font=plain_ui_font(12))
        self.minus_box.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.plus_box = ctk.CTkTextbox(tags_row, height=120, font=plain_ui_font(12))
        self.plus_box.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        self.signals_label = ctk.CTkLabel(
            self,
            text="",
            anchor="w",
            justify="left",
            wraplength=720,
            text_color=("gray30", "gray70"),
        )
        self.signals_label.grid(row=6, column=0, sticky="ew", pady=(8, 0))

    def _save(self) -> None:
        save_user_profile(
            {
                "name": self.name_entry.get().strip(),
                "age": self.age_entry.get().strip(),
                "city": self.city_entry.get().strip(),
                "bio": self.bio_box.get("1.0", "end").strip(),
            }
        )

    def _analyze(self) -> None:
        self._save()
        bio = self.bio_box.get("1.0", "end").strip()
        name = self.name_entry.get().strip()
        city = self.city_entry.get().strip()
        age_raw = self.age_entry.get().strip()
        try:
            age = int(age_raw) if age_raw else None
        except ValueError:
            age = None

        header = f"{name}, {age or '?'}, {city}"
        raw = f"{header} – {bio}" if bio else header

        result, _media, signals = analyze_profile_trash(
            raw_text=raw,
            name=name,
            age=age,
            word_count=None,
            media_rows=[],
            base_dir=self.base_dir,
        )

        score_text = format_trash_percent(result.score)
        populate_trash_summary_colored(
            self.result_summary,
            f"Мусорность: {score_text} · {result.label}",
            score=result.score,
        )
        populate_trash_tag_panels(self.minus_box, self.plus_box, result.tags)

        parts = []
        if signals.universities:
            parts.append(f"Вузы: {', '.join(signals.universities)}")
        if signals.artists:
            parts.append(f"Музыка: {', '.join(signals.artists)}")
        if signals.fandoms:
            parts.append(f"ФД: {', '.join(signals.fandoms)}")
        if signals.games:
            parts.append(f"Игры: {', '.join(signals.games)}")
        if signals.location:
            parts.append(f"Локация: {signals.location}")
        if signals.tone:
            parts.append(f"Тон: {', '.join(signals.tone)}")
        if signals.metro:
            parts.append(f"Метро: {', '.join(signals.metro)}")
        self.signals_label.configure(text=" · ".join(parts) or "Сигналы не найдены")
