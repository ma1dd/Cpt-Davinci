"""Редактор правил скоринга (+/− бонусы)."""
from __future__ import annotations

import customtkinter as ctk

from gui.emoji_text import plain_ui_font
from services.signal_catalog import get_scoring_rules, reload_catalog, update_rule_override

_HEAVY_LABELS = ("лёг.", "тяж.")


class RulesPage(ctk.CTkFrame):
    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.scroll = ctk.CTkScrollableFrame(self, label_text="")
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

        self._rows: list[dict] = []
        self.refresh()

    def refresh(self) -> None:
        reload_catalog()
        for child in self.scroll.winfo_children():
            child.destroy()
        self._rows.clear()

        for index, rule in enumerate(get_scoring_rules()):
            row = ctk.CTkFrame(self.scroll, fg_color=("gray88", "gray20"), corner_radius=8)
            row.grid(row=index, column=0, sticky="ew", pady=3, padx=2)
            row.grid_columnconfigure(1, weight=1)

            enabled_var = ctk.BooleanVar(value=rule.enabled)
            enabled = ctk.CTkCheckBox(
                row,
                text="",
                variable=enabled_var,
                width=24,
                command=lambda rid=rule.id, var=enabled_var: self._toggle(rid, var),
            )
            enabled.grid(row=0, column=0, rowspan=2, padx=(6, 2), pady=6)

            title = f"{rule.label}  ({rule.id})"
            if rule.tag_only:
                title += "  [только тег]"
            if rule.per_match:
                title += "  [×N]"
            ctk.CTkLabel(
                row,
                text=title,
                anchor="w",
                font=plain_ui_font(13),
                wraplength=520,
                justify="left",
            ).grid(row=0, column=1, sticky="ew", padx=4, pady=(6, 0))

            ctk.CTkLabel(
                row,
                text=rule.pattern,
                anchor="w",
                font=ctk.CTkFont(size=10),
                text_color=("gray40", "gray65"),
                wraplength=520,
                justify="left",
            ).grid(row=1, column=1, sticky="ew", padx=4, pady=(0, 6))

            delta_entry = ctk.CTkEntry(row, width=64, height=28, justify="center")
            sign = "+" if rule.delta >= 0 else ""
            delta_entry.insert(
                0,
                f"{sign}{int(rule.delta) if rule.delta == int(rule.delta) else rule.delta}",
            )
            delta_entry.grid(row=0, column=2, rowspan=2, padx=(4, 4), pady=6)
            delta_entry.bind(
                "<FocusOut>",
                lambda _e, rid=rule.id, entry=delta_entry: self._save_delta(rid, entry),
            )
            delta_entry.bind(
                "<Return>",
                lambda _e, rid=rule.id, entry=delta_entry: self._save_delta(rid, entry),
            )

            heavy_menu = ctk.CTkOptionMenu(
                row,
                values=list(_HEAVY_LABELS),
                width=72,
                height=28,
                font=ctk.CTkFont(size=12),
                command=lambda val, rid=rule.id: self._save_heavy(rid, val),
            )
            heavy_menu.set("тяж." if rule.heavy else "лёг.")
            heavy_menu.grid(row=0, column=3, rowspan=2, padx=(0, 6), pady=6)

            self._rows.append(
                {"id": rule.id, "enabled": enabled_var, "delta": delta_entry, "heavy": heavy_menu}
            )

    def _toggle(self, rule_id: str, var: ctk.BooleanVar) -> None:
        update_rule_override(rule_id, enabled=var.get())

    def _save_delta(self, rule_id: str, entry: ctk.CTkEntry) -> None:
        raw = entry.get().strip().replace(",", ".").replace("+", "")
        if not raw:
            return
        try:
            value = float(raw)
        except ValueError:
            return
        update_rule_override(rule_id, delta=value)

    def _save_heavy(self, rule_id: str, label: str) -> None:
        update_rule_override(rule_id, heavy=(label == "тяж."))
