"""Порционная отрисовка строк в CTkScrollableFrame без пагинации."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from gui.profile_row import create_profile_row

LIST_CHUNK_SIZE = 40
SCROLL_LOAD_THRESHOLD = 0.85

RowItem = tuple[str, str, float | None, Callable[[], None]]
RowFactory = Callable[[ctk.CTkFrame, RowItem], ctk.CTkFrame]


def _default_row_factory(parent: ctk.CTkFrame, item: RowItem) -> ctk.CTkFrame:
    title, reaction_label, trash_score, command = item
    row = create_profile_row(
        parent,
        title=title,
        reaction_label=reaction_label,
        trash_score=trash_score,
        command=command,
    )
    row.pack(fill="x", pady=2)
    return row


class IncrementalProfileList:
    def __init__(
        self,
        parent: ctk.CTkScrollableFrame,
        *,
        row_factory: RowFactory | None = None,
        chunk_size: int = LIST_CHUNK_SIZE,
    ) -> None:
        self._parent = parent
        self._row_factory = row_factory or _default_row_factory
        self._chunk_size = chunk_size
        self._items: list[RowItem] = []
        self._rendered = 0
        self._generation = 0
        self._scroll_bound = False
        self._pending_after: str | None = None

    def reset(self, items: list[RowItem]) -> None:
        self._cancel_pending()
        self._generation += 1
        self._items = items
        self._rendered = 0
        for child in self._parent.winfo_children():
            child.destroy()
        self._ensure_scroll_bind()
        self._schedule_append()

    def _cancel_pending(self) -> None:
        if self._pending_after is not None:
            try:
                self._parent.after_cancel(self._pending_after)
            except (tk.TclError, ValueError):
                pass
            self._pending_after = None

    def _canvas(self) -> tk.Canvas:
        return self._parent._parent_canvas

    def _ensure_scroll_bind(self) -> None:
        if self._scroll_bound:
            return
        self._scroll_bound = True
        canvas = self._canvas()
        canvas.bind("<Configure>", lambda _event: self._schedule_load_more(), add="+")
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.bind(sequence, lambda _event: self._schedule_load_more(), add="+")

    def _schedule_load_more(self) -> None:
        if self._pending_after is not None:
            return
        self._pending_after = self._parent.after_idle(self._load_more_if_needed)

    def _schedule_append(self) -> None:
        if self._pending_after is not None:
            return
        self._pending_after = self._parent.after_idle(self._append_chunk)

    def _load_more_if_needed(self) -> None:
        self._pending_after = None
        if self._rendered >= len(self._items):
            return
        try:
            _top, bottom = self._canvas().yview()
        except tk.TclError:
            return
        if bottom >= SCROLL_LOAD_THRESHOLD:
            self._append_chunk()

    def _append_chunk(self) -> None:
        self._pending_after = None
        if self._rendered >= len(self._items):
            return

        generation = self._generation
        end = min(self._rendered + self._chunk_size, len(self._items))
        for item in self._items[self._rendered:end]:
            if generation != self._generation:
                return
            self._row_factory(self._parent, item)
        self._rendered = end

        if self._rendered >= len(self._items):
            return

        self._parent.update_idletasks()
        try:
            _top, bottom = self._canvas().yview()
        except tk.TclError:
            bottom = 1.0
        if bottom >= SCROLL_LOAD_THRESHOLD:
            self._schedule_append()
