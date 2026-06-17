"""Цветные эмодзи в стиле Apple (близко к Telegram на iOS) для CTkTextbox."""
from __future__ import annotations

import re

import customtkinter as ctk
from pathlib import Path

from PIL import Image, ImageTk
from pilmoji.helpers import EMOJI_REGEX, NodeType, to_nodes
from pilmoji.source import AppleEmojiSource

# Telegram на iOS/macOS — Apple-эмодзи; на Android — Google.
EMOJI_SOURCE = AppleEmojiSource()
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "emoji_cache"
EMOJI_SCALE = 1.1
TEXT_FONT_REACTION = 13
TEXT_FONT_DESCRIPTION = 14


class EmojiRenderer:
    def __init__(self, cache_dir: Path = CACHE_DIR) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._photos: dict[tuple[str, int], ImageTk.PhotoImage] = {}

    def _cache_path(self, emoji_char: str) -> Path:
        codepoints = "-".join(f"{ord(ch):x}" for ch in emoji_char)
        return self.cache_dir / f"{codepoints}.png"

    def _load_pil(self, emoji_char: str) -> Image.Image | None:
        cached = self._cache_path(emoji_char)
        if cached.is_file():
            with Image.open(cached) as image:
                return image.convert("RGBA")

        stream = EMOJI_SOURCE.get_emoji(emoji_char)
        if stream is None:
            return None

        with Image.open(stream) as image:
            frame = image.convert("RGBA")
        frame.save(cached, "PNG")
        return frame

    def get_photo(self, emoji_char: str, *, size: int) -> ImageTk.PhotoImage | None:
        key = (emoji_char, size)
        if key in self._photos:
            return self._photos[key]

        pil = self._load_pil(emoji_char)
        if pil is None:
            return None

        target = max(16, int(size * EMOJI_SCALE))
        pil = pil.resize((target, target), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(pil)
        self._photos[key] = photo
        return photo


_renderer = EmojiRenderer()


def plain_ui_font(size: int = 14) -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=size)


def emoji_ui_font(size: int = 14) -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI Emoji", size=size)


def configure_copyable_readonly(textbox: ctk.CTkTextbox) -> None:
    """Только чтение, но с возможностью выделения и Ctrl+C."""

    def on_key(event) -> str | None:
        if event.state & 0x4:
            if event.keysym.lower() in {"c", "a", "x"}:
                return None
            if event.keysym.lower() == "insert":
                return None
        if event.keysym in {
            "Left",
            "Right",
            "Up",
            "Down",
            "Home",
            "End",
            "Prior",
            "Next",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
        }:
            return None
        return "break"

    inner = textbox._textbox
    inner.bind("<Key>", on_key, add="+")
    inner.configure(exportselection=True)


def _append_emoji_text(
    tw,
    text: str,
    refs: list[ImageTk.PhotoImage],
    *,
    font_size: int,
    tag: str | None = None,
) -> None:
    emoji_size = font_size + 1
    lines = to_nodes(text or "")
    for line_index, line_nodes in enumerate(lines):
        for node in line_nodes:
            if node.type is NodeType.emoji:
                photo = _renderer.get_photo(node.content, size=emoji_size)
                if photo:
                    refs.append(photo)
                    tw.image_create("end", image=photo, padx=1, pady=1)
                elif tag:
                    tw.insert("end", node.content, tag)
                else:
                    tw.insert("end", node.content)
            elif tag:
                tw.insert("end", node.content, tag)
            else:
                tw.insert("end", node.content)
        if line_index < len(lines) - 1:
            tw.insert("end", "\n", tag) if tag else tw.insert("end", "\n")


def populate_emoji_textbox(
    textbox: ctk.CTkTextbox,
    text: str,
    *,
    font_size: int = TEXT_FONT_REACTION,
    readonly: bool = True,
) -> None:
    """Вставляет текст со встроенными цветными эмодзи (Apple / Telegram-like)."""
    tw = textbox._textbox
    tw.configure(state="normal")
    tw.delete("1.0", "end")
    tw.configure(font=("Segoe UI", font_size))

    refs: list[ImageTk.PhotoImage] = []
    textbox._emoji_photo_refs = refs

    emoji_size = font_size + 1
    lines = to_nodes(text or "")
    for line_index, line_nodes in enumerate(lines):
        for node in line_nodes:
            if node.type is NodeType.emoji:
                photo = _renderer.get_photo(node.content, size=emoji_size)
                if photo:
                    refs.append(photo)
                    tw.image_create("end", image=photo, padx=1, pady=1)
                else:
                    tw.insert("end", node.content)
            else:
                tw.insert("end", node.content)
        if line_index < len(lines) - 1:
            tw.insert("end", "\n")

    if readonly:
        configure_copyable_readonly(textbox)
    else:
        tw.configure(state="normal")



def emoji_to_ctk_image(emoji_char: str, *, size: int = 18) -> ctk.CTkImage | None:
    pil = _renderer._load_pil(emoji_char)
    if pil is None:
        return None
    target = max(14, int(size * EMOJI_SCALE))
    pil = pil.resize((target, target), Image.Resampling.LANCZOS)
    return ctk.CTkImage(pil, size=(target, target))


def warm_emoji_cache() -> None:
    """Предзагрузка частых эмодзи (кэш на диск, без повторной загрузки)."""
    common = (
        "❤️❤👎😀😊🔥✨💕🎉👋🙈😍🥰😭💋💞💬😂🤔👀✅❌🚫"
        "👍😬🗑🚮☣️💀⚰️😈🤪"
    )
    for match in EMOJI_REGEX.finditer(common):
        _renderer.get_photo(match.group(), size=18)


def trash_score_color(score: float | None) -> str:
    if score is None:
        return "#888888"
    if score <= 40:
        return "#6fdc8c"
    if score <= 80:
        return "#f0c14b"
    return "#ff7b72"


def populate_trash_summary_colored(
    textbox: ctk.CTkTextbox,
    text: str,
    *,
    score: float | None = None,
    font_size: int = 14,
    readonly: bool = True,
) -> None:
    tw = textbox._textbox
    tw.configure(state="normal")
    tw.delete("1.0", "end")
    tw.configure(font=("Segoe UI", font_size))

    refs: list[ImageTk.PhotoImage] = []
    textbox._emoji_photo_refs = refs

    percent_match = re.search(r"(\d+%)", text or "")
    if percent_match and score is not None:
        start = percent_match.start(1)
        end = percent_match.end(1)
        _append_emoji_text(tw, text[:start], refs, font_size=font_size)
        tw.insert("end", percent_match.group(1), ("trash_pct",))
        tw.tag_configure("trash_pct", foreground=trash_score_color(score))
        _append_emoji_text(tw, text[end:], refs, font_size=font_size)
    else:
        _append_emoji_text(tw, text or "", refs, font_size=font_size)

    if readonly:
        configure_copyable_readonly(textbox)
    else:
        tw.configure(state="normal")


def populate_trash_tags_list(
    textbox: ctk.CTkTextbox,
    tags,
) -> None:
    """Один список плюсов и минусов без цветовой подсветки."""
    tw = textbox._textbox
    tw.configure(state="normal")
    tw.delete("1.0", "end")
    tw.configure(font=("Segoe UI", 12))
    for item in tags:
        tw.insert("end", item.display() + "\n")
    configure_copyable_readonly(textbox)


def populate_trash_tag_panels(
    minus_box: ctk.CTkTextbox,
    plus_box: ctk.CTkTextbox,
    tags,
) -> None:
    minus_items = [tag for tag in tags if tag.delta < 0]
    plus_items = [tag for tag in tags if tag.delta >= 0]

    for box, items, tag_name, color in (
        (minus_box, minus_items, "minus", "#3fb950"),
        (plus_box, plus_items, "plus", "#ff7b72"),
    ):
        tw = box._textbox
        tw.configure(state="normal")
        tw.delete("1.0", "end")
        tw.configure(font=("Segoe UI", 12))
        tw.tag_configure(tag_name, foreground=color)
        refs: list[ImageTk.PhotoImage] = []
        box._emoji_photo_refs = refs
        for item in items:
            _append_emoji_text(tw, item.display(), refs, font_size=12, tag=tag_name)
            tw.insert("end", "\n", tag_name)
        configure_copyable_readonly(box)


def estimate_textbox_height(
    text: str,
    font_size: int,
    *,
    min_height: int = 36,
    max_height: int = 220,
) -> int:
    lines = max(1, len((text or "").splitlines()))
    return min(max_height, max(min_height, lines * (font_size + 10) + 12))
