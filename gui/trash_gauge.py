"""Круговой индикатор доли анкет с мусорностью > 90%."""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk


def _resolve_ctk_color(color) -> str:
    """Один цвет для tk.Canvas из значения fg_color CustomTkinter."""
    if isinstance(color, (list, tuple)):
        idx = 0 if ctk.get_appearance_mode().lower() == "light" else 1
        return str(color[idx] if idx < len(color) else color[0])
    if isinstance(color, str):
        parts = color.split()
        if len(parts) >= 2:
            idx = 0 if ctk.get_appearance_mode().lower() == "light" else 1
            return parts[idx]
        return color
    return "#2b2b2b"


class TrashOver90Gauge(ctk.CTkFrame):
    def __init__(self, master, *, size: int = 96, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._size = size
        self._value: float | None = None

        try:
            raw = master.cget("fg_color")
        except (AttributeError, tk.TclError):
            raw = ctk.ThemeManager.theme["CTkFrame"]["fg_color"]
        self._bg = _resolve_ctk_color(raw)

        self.canvas = tk.Canvas(
            self,
            width=size,
            height=size,
            highlightthickness=0,
            bg=self._bg,
        )
        self.canvas.pack()

    def set_value(self, percent: float | None) -> None:
        self._value = percent
        self._redraw()

    def _redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        s = self._size
        pad = 8
        x0, y0, x1, y1 = pad, pad, s - pad, s - pad

        c.create_oval(x0, y0, x1, y1, outline="#444444", width=6)

        if self._value is not None and self._value > 0:
            extent = -360 * min(self._value, 100) / 100
            color = "#cf222e" if self._value >= 25 else "#9a6700"
            c.create_arc(
                x0,
                y0,
                x1,
                y1,
                start=90,
                extent=extent,
                outline=color,
                width=6,
                style="arc",
            )

        text = "—" if self._value is None else f"{self._value:.0f}%"
        c.create_text(s / 2, s / 2, text=text, fill="#eeeeee", font=("Segoe UI", 14, "bold"))
