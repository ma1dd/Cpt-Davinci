"""Строка анкеты в списке: текст + мусорность + реакции."""
from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from gui.emoji_text import emoji_to_ctk_image, emoji_ui_font, plain_ui_font
from services.trash_analyzer import format_trash_percent

_BADGE_ALIASES = {"❤": "❤️"}
_FONT_SIZE = 13
_EMOJI_SIZE = 16
_MAX_TITLE_LEN = 48
_ROW_PADY = 7


def reaction_emojis_from_label(label: str) -> list[str]:
    if not label or label == "—":
        return []
    return [_BADGE_ALIASES.get(part, part) for part in label.split()]


def _bind_click(widget, command: Callable[[], None]) -> None:
    widget.bind("<Button-1>", lambda _event: command())
    for child in widget.winfo_children():
        _bind_click(child, command)


def _compact_title(title: str) -> str:
    text = (title or "").strip() or "Без имени"
    if len(text) <= _MAX_TITLE_LEN:
        return text
    return text[: _MAX_TITLE_LEN - 1].rstrip() + "…"


def _trash_color(score: float | None) -> tuple[str, str]:
    if score is None:
        return ("gray40", "gray65")
    if score <= 40:
        return ("#1a7f37", "#6fdc8c")
    if score <= 80:
        return ("#9a6700", "#f0c14b")
    return ("#cf222e", "#ff7b72")


def create_profile_row(
    parent,
    *,
    title: str,
    reaction_label: str,
    trash_score: float | None = None,
    command: Callable[[], None],
    fast_badges: bool = False,
) -> ctk.CTkFrame:
    row = ctk.CTkFrame(
        parent,
        fg_color=("gray82", "gray20"),
        corner_radius=8,
        cursor="hand2",
    )
    row.grid_columnconfigure(1, weight=1)

    trash_text = format_trash_percent(trash_score)
    trash_label = ctk.CTkLabel(
        row,
        text=trash_text,
        width=44,
        anchor="e",
        font=plain_ui_font(12),
        text_color=_trash_color(trash_score),
    )
    trash_label.grid(row=0, column=0, sticky="w", padx=(10, 4), pady=_ROW_PADY)

    title_label = ctk.CTkLabel(
        row,
        text=_compact_title(title),
        anchor="w",
        font=plain_ui_font(_FONT_SIZE),
        height=20,
    )
    title_label.grid(row=0, column=1, sticky="ew", padx=(0, 4), pady=_ROW_PADY)

    badge_frame = ctk.CTkFrame(row, fg_color="transparent")
    badge_frame.grid(row=0, column=2, sticky="e", padx=(0, 10), pady=_ROW_PADY)

    emoji_refs: list[ctk.CTkImage] = []
    emojis = reaction_emojis_from_label(reaction_label)
    if not emojis:
        spacer = ctk.CTkFrame(badge_frame, fg_color="transparent", width=1, height=20)
        spacer.pack()
        spacer.pack_propagate(False)
    else:
        for emoji_char in emojis:
            if fast_badges:
                badge = ctk.CTkLabel(
                    badge_frame,
                    text=emoji_char,
                    font=emoji_ui_font(_FONT_SIZE),
                    width=20,
                    height=20,
                )
            else:
                image = emoji_to_ctk_image(emoji_char, size=_EMOJI_SIZE)
                if image:
                    emoji_refs.append(image)
                    badge = ctk.CTkLabel(
                        badge_frame,
                        text="",
                        image=image,
                        width=_EMOJI_SIZE + 4,
                        height=_EMOJI_SIZE + 4,
                    )
                else:
                    badge = ctk.CTkLabel(
                        badge_frame,
                        text=emoji_char,
                        font=emoji_ui_font(_FONT_SIZE),
                        width=20,
                        height=20,
                    )
            badge.pack(side="left", padx=1)

    row._emoji_refs = emoji_refs
    _bind_click(row, command)
    return row


def populate_profile_rows(
    parent,
    items: list[tuple[str, str, float | None, Callable[[], None]]],
) -> None:
    for child in parent.winfo_children():
        child.destroy()

    for title, reaction_label, trash_score, command in items:
        row = create_profile_row(
            parent,
            title=title,
            reaction_label=reaction_label,
            trash_score=trash_score,
            command=command,
        )
        row.pack(fill="x", pady=2)
