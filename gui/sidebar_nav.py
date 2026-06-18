"""Вертикальная навигация в стиле Telegram."""
from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk


class SidebarNav(ctk.CTkFrame):
    _ACTIVE = ("#2d5f8f", "#1e4a6e")
    _HOVER = ("gray82", "gray28")
    _INACTIVE = "transparent"

    def __init__(
        self,
        master,
        *,
        on_select: Callable[[str], None],
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._on_select = on_select
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._active = "browse"

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text="LeoMatch",
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
            text_color=("gray20", "gray90"),
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(4, 2))

        ctk.CTkLabel(
            self,
            text="просмотр анкет",
            font=ctk.CTkFont(size=11),
            anchor="w",
            text_color=("gray45", "gray60"),
        ).grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))

        divider = ctk.CTkFrame(self, height=1, fg_color=("gray78", "gray30"))
        divider.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))

        items = (
            ("browse", "🏠", "Обзор"),
            ("rules", "⚙", "Правила"),
            ("profile", "👤", "Профиль"),
            ("corpus", "📊", "Корпус"),
        )
        for index, (key, icon, label) in enumerate(items):
            btn = ctk.CTkButton(
                self,
                text=f"  {icon}   {label}",
                anchor="w",
                height=42,
                corner_radius=10,
                font=ctk.CTkFont(size=14),
                fg_color=self._INACTIVE,
                hover_color=self._HOVER,
                border_width=0,
                command=lambda k=key: self._select(k),
            )
            btn.grid(row=3 + index, column=0, sticky="ew", padx=6, pady=2)
            self._buttons[key] = btn

        self.grid_rowconfigure(7, weight=1)
        self._highlight()

    def _select(self, key: str) -> None:
        self._active = key
        self._highlight()
        self._on_select(key)

    def _highlight(self) -> None:
        for key, btn in self._buttons.items():
            if key == self._active:
                btn.configure(fg_color=self._ACTIVE, hover_color=self._ACTIVE)
            else:
                btn.configure(fg_color=self._INACTIVE, hover_color=self._HOVER)

    def set_active(self, key: str) -> None:
        self._active = key
        self._highlight()
