"""Фильтр реакций с цветными Apple-эмодзи (не системный шрифт)."""
from __future__ import annotations

import customtkinter as ctk

from gui.emoji_text import emoji_to_ctk_image, plain_ui_font

_EMOJI_SIZE = 16


def _split_option(label: str) -> tuple[str | None, str]:
    text = label.strip()
    if text == "Все":
        return None, text
    parts = text.split(" ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, text


class ReactionPicker(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        labels: list[str],
        width: int = 240,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._labels = labels
        self._current = labels[0] if labels else ""
        self._width = width
        self._popup: ctk.CTkToplevel | None = None
        self._image_refs: list[ctk.CTkImage] = []

        self._button = ctk.CTkFrame(
            self,
            fg_color=("gray84", "gray25"),
            corner_radius=6,
            border_width=2,
            border_color=("gray70", "gray35"),
            cursor="hand2",
        )
        self._button.pack(fill="x")
        self._button.bind("<Button-1>", lambda _e: self._toggle_popup())

        inner = ctk.CTkFrame(self._button, fg_color="transparent")
        inner.pack(fill="x", padx=8, pady=6)
        inner.bind("<Button-1>", lambda _e: self._toggle_popup())

        self._emoji_label = ctk.CTkLabel(inner, text="", width=_EMOJI_SIZE + 4)
        self._emoji_label.pack(side="left", padx=(0, 6))
        self._emoji_label.bind("<Button-1>", lambda _e: self._toggle_popup())

        self._text_label = ctk.CTkLabel(
            inner,
            text="",
            anchor="w",
            font=plain_ui_font(13),
        )
        self._text_label.pack(side="left", fill="x", expand=True)
        self._text_label.bind("<Button-1>", lambda _e: self._toggle_popup())

        chevron = ctk.CTkLabel(inner, text="▼", width=16, font=plain_ui_font(11))
        chevron.pack(side="right")
        chevron.bind("<Button-1>", lambda _e: self._toggle_popup())

        self._set_display(self._current)

    def get(self) -> str:
        return self._current

    def set(self, value: str) -> None:
        if value in self._labels:
            self._current = value
            self._set_display(value)

    def _set_display(self, label: str) -> None:
        emoji_char, text = _split_option(label)
        image = emoji_to_ctk_image(emoji_char, size=_EMOJI_SIZE) if emoji_char else None
        if image:
            self._image_refs = [image]
            self._emoji_label.configure(image=image, text="")
        else:
            self._image_refs = []
            self._emoji_label.configure(image=None, text="")
        self._text_label.configure(text=text if emoji_char else label)

    def _toggle_popup(self) -> None:
        if self._popup is not None and self._popup.winfo_exists():
            self._close_popup()
            return
        self._open_popup()

    def _open_popup(self) -> None:
        self._popup = ctk.CTkToplevel(self)
        self._popup.overrideredirect(True)
        self._popup.attributes("-topmost", True)
        self._popup.configure(fg_color=("gray90", "gray20"))

        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        self._popup.geometry(f"{self._width}x{min(220, 36 * len(self._labels) + 8)}+{x}+{y}")

        panel = ctk.CTkFrame(
            self._popup,
            fg_color=("gray90", "gray20"),
            corner_radius=6,
            border_width=2,
            border_color=("gray70", "gray35"),
        )
        panel.pack(fill="both", expand=True)

        popup_refs: list[ctk.CTkImage] = []
        for label in self._labels:
            row = ctk.CTkFrame(panel, fg_color="transparent", cursor="hand2")
            row.pack(fill="x", padx=4, pady=2)

            emoji_char, text = _split_option(label)
            image = emoji_to_ctk_image(emoji_char, size=_EMOJI_SIZE) if emoji_char else None
            if image:
                popup_refs.append(image)
                emoji_widget = ctk.CTkLabel(row, text="", image=image, width=_EMOJI_SIZE + 4)
            else:
                emoji_widget = ctk.CTkLabel(row, text="", width=_EMOJI_SIZE + 4)
            emoji_widget.pack(side="left", padx=(6, 6))

            text_widget = ctk.CTkLabel(row, text=text if emoji_char else label, anchor="w")
            text_widget.pack(side="left", fill="x", expand=True, padx=(0, 6))

            def pick(selected: str = label) -> None:
                self._current = selected
                self._set_display(selected)
                self._close_popup()

            for widget in (row, emoji_widget, text_widget):
                widget.bind("<Button-1>", lambda _e, s=label: pick(s))

        self._popup._emoji_refs = popup_refs
        self._popup.bind("<FocusOut>", lambda _e: self.after(80, self._close_popup))
        self.winfo_toplevel().bind("<Button-1>", self._on_click_outside, add="+")

    def _on_click_outside(self, event) -> None:
        if self._popup is None or not self._popup.winfo_exists():
            self.winfo_toplevel().unbind("<Button-1>")
            return
        widget = event.widget
        while widget is not None:
            if widget == self._popup or widget == self._button:
                return
            widget = widget.master
        self._close_popup()
        self.winfo_toplevel().unbind("<Button-1>")

    def _close_popup(self) -> None:
        if self._popup is not None:
            try:
                if self._popup.winfo_exists():
                    self._popup.destroy()
            except Exception:
                pass
            self._popup = None
        try:
            self.winfo_toplevel().unbind("<Button-1>")
        except Exception:
            pass
