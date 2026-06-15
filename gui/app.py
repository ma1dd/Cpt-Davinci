import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image

from database.viewer_queries import (
    FilterParams,
    PeriodFilter,
    ProfileSummary,
    ProfileViewerRepository,
    ReactionFilter,
    build_description,
    build_summary_title,
    build_title,
    format_reaction_status,
)
from gui.icons import load_reaction_icons, reaction_icon_key
from gui.media import (
    MEDIA_SIZE,
    collect_resolved_media,
    load_display_image,
    media_caption,
    open_media_externally,
)
from viewer_config import ViewerSettings, load_viewer_settings

SIDEBAR_WIDTH = 310
REACTION_OPTIONS = {
    "Все": ReactionFilter.ALL,
    "Лайк": ReactionFilter.LIKE,
    "Дизлайк": ReactionFilter.DISLIKE,
    "С комментарием": ReactionFilter.COMMENT,
    "Взаимные лайки": ReactionFilter.MUTUAL,
}
PERIOD_OPTIONS = {
    "За всё время": PeriodFilter.ALL,
    "За сегодня": PeriodFilter.TODAY,
    "За неделю": PeriodFilter.WEEK,
}


class ProfileViewerApp(ctk.CTk):
    def __init__(self, settings: ViewerSettings) -> None:
        super().__init__()
        self.settings = settings
        self.repo = ProfileViewerRepository(settings.db_path)

        self.title("LeoMatch — просмотр анкет")
        self.geometry("1220x780")
        self.minsize(1020, 680)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.profile_ids: list[int] = []
        self.profile_summaries: list[ProfileSummary] = []
        self.current_index = 0
        self.current_media_index = 0
        self.current_media_paths: list = []
        self.current_view = "home"
        self._nav_back: list[dict] = []
        self._nav_forward: list[dict] = []
        self._pil_image: Image.Image | None = None
        self._ctk_image: ctk.CTkImage | None = None
        self._age_validate = (self.register(self._validate_digits), "%P")
        self._reaction_icons = load_reaction_icons()

        self._build_layout()
        self._bind_navigation_keys()
        self._load_city_options()
        self._show_home(record_history=False)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=SIDEBAR_WIDTH)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_content_area()

    def _build_sidebar(self) -> None:
        self.sidebar = ctk.CTkFrame(self, width=SIDEBAR_WIDTH, corner_radius=12)
        self.sidebar.grid(row=0, column=0, sticky="ns", padx=(16, 8), pady=16)
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(1, weight=0)

        scroll = ctk.CTkScrollableFrame(self.sidebar, label_text="Фильтры", height=520)
        scroll.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        scroll.grid_columnconfigure(0, weight=1)

        self.keyword_entry = self._sidebar_entry(scroll, 0, "Поиск по описанию")
        self.city_option = self._sidebar_option(scroll, 1, "Город", ["— любой —"])
        self.age_from_entry = self._sidebar_entry(
            scroll, 2, "Возраст от", digits_only=True
        )
        self.age_to_entry = self._sidebar_entry(
            scroll, 3, "Возраст до", digits_only=True
        )
        self.age_from_entry.insert(0, "18")
        self.age_to_entry.insert(0, "99")
        self.reaction_option = self._sidebar_option(
            scroll, 4, "Реакция", list(REACTION_OPTIONS.keys())
        )
        self.period_option = self._sidebar_option(
            scroll, 5, "Период", list(PERIOD_OPTIONS.keys())
        )

        ctk.CTkLabel(
            scroll,
            text="Все фильтры работают по логике «И».",
            wraplength=240,
            justify="left",
            text_color=("gray30", "gray70"),
        ).grid(row=12, column=0, sticky="w", padx=4, pady=(8, 4))

        bottom = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        bottom.grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 12))
        bottom.grid_columnconfigure(0, weight=1)

        self.apply_button = ctk.CTkButton(
            bottom,
            text="Применить фильтры",
            height=42,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._apply_filters,
        )
        self.apply_button.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.reset_button = ctk.CTkButton(
            bottom,
            text="Сбросить фильтры",
            height=36,
            fg_color=("gray75", "gray25"),
            hover_color=("gray65", "gray35"),
            command=self._reset_filters,
        )
        self.reset_button.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self.home_sidebar_button = ctk.CTkButton(
            bottom,
            text="На главный экран",
            height=36,
            fg_color=("gray75", "gray25"),
            hover_color=("gray65", "gray35"),
            command=lambda: self._show_home(record_history=True),
        )
        self.home_sidebar_button.grid(row=2, column=0, sticky="ew")

    def _build_content_area(self) -> None:
        self.content = ctk.CTkFrame(self, corner_radius=12)
        self.content.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=16)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        self.header = ctk.CTkFrame(self.content, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        self.header.grid_columnconfigure(1, weight=1)

        title_wrap = ctk.CTkFrame(self.header, fg_color="transparent")
        title_wrap.grid(row=0, column=0, sticky="w")

        self.page_title = ctk.CTkLabel(
            title_wrap,
            text="Главная",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self.page_title.pack(side="left")

        self.header_info_label = ctk.CTkLabel(
            title_wrap,
            text="",
            font=ctk.CTkFont(size=14),
            text_color=("gray30", "gray70"),
        )
        self.header_info_label.pack(side="left", padx=(12, 0))

        nav_wrap = ctk.CTkFrame(self.header, fg_color="transparent")
        nav_wrap.grid(row=0, column=2, sticky="e")

        self.refresh_button = ctk.CTkButton(
            nav_wrap,
            text="Обновить",
            width=100,
            command=self._refresh_current_view,
        )
        self.refresh_button.pack(side="left", padx=(0, 16))

        history_nav = ctk.CTkFrame(nav_wrap, fg_color="transparent")
        history_nav.pack(side="left")

        self.nav_back_button = ctk.CTkButton(
            history_nav,
            text="◀ Назад",
            width=90,
            command=self._go_back,
        )
        self.nav_back_button.pack(side="left", padx=(0, 8))

        self.nav_forward_button = ctk.CTkButton(
            history_nav,
            text="Вперёд ▶",
            width=90,
            command=self._go_forward,
        )
        self.nav_forward_button.pack(side="left", padx=(0, 12))

        self.profile_prev_button = ctk.CTkButton(
            history_nav,
            text="◀ Пред.",
            width=90,
            command=self._show_previous,
        )
        self.profile_next_button = ctk.CTkButton(
            history_nav,
            text="След. ▶",
            width=90,
            command=self._show_next,
        )

        self.body = ctk.CTkFrame(self.content, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 16))
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)

        self.home_frame = ctk.CTkFrame(self.body, fg_color="transparent")
        self.list_frame = ctk.CTkFrame(self.body, fg_color="transparent")
        self.detail_frame = ctk.CTkFrame(self.body, fg_color="transparent")

        for frame in (self.home_frame, self.list_frame, self.detail_frame):
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)

        self._build_home_page()
        self._build_list_page()
        self._build_detail_page()

    def _build_home_page(self) -> None:
        wrap = ctk.CTkScrollableFrame(self.home_frame, label_text="Статистика")
        wrap.grid(row=0, column=0, sticky="nsew")
        wrap.grid_columnconfigure((0, 1), weight=1)

        self.stat_labels: dict[str, ctk.CTkLabel] = {}
        cards = [
            ("profiles", "Всего анкет"),
            ("likes", "Лайков"),
            ("dislikes", "Дизлайков"),
            ("comments", "С комментарием"),
            ("mutual_likes", "Взаимных лайков"),
            ("with_media", "С медиа"),
        ]
        for index, (key, title) in enumerate(cards):
            card = ctk.CTkFrame(wrap, corner_radius=12)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=8, pady=8)
            ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=14)).pack(
                anchor="w", padx=16, pady=(16, 4)
            )
            value_label = ctk.CTkLabel(
                card, text="0", font=ctk.CTkFont(size=34, weight="bold")
            )
            value_label.pack(anchor="w", padx=16, pady=(0, 16))
            self.stat_labels[key] = value_label

        ctk.CTkLabel(
            wrap,
            text="Последние анкеты",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(16, 8))

        self.latest_profiles_frame = ctk.CTkFrame(wrap, fg_color="transparent")
        self.latest_profiles_frame.grid(
            row=5, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8)
        )
        self.latest_profiles_frame.grid_columnconfigure(0, weight=1)

    def _build_list_page(self) -> None:
        self.list_frame.grid_rowconfigure(0, weight=1)

        self.list_scroll = ctk.CTkScrollableFrame(self.list_frame, label_text="Результаты")
        self.list_scroll.grid(row=0, column=0, sticky="nsew")
        self.list_scroll.grid_columnconfigure(0, weight=1)

        self.list_empty_label = ctk.CTkLabel(
            self.list_frame,
            text="",
            text_color=("gray35", "gray70"),
        )

    def _build_detail_page(self) -> None:
        self.detail_frame.grid_rowconfigure(1, weight=1)

        content_row = ctk.CTkFrame(self.detail_frame, fg_color="transparent")
        content_row.grid(row=0, column=0, sticky="nsew")
        content_row.grid_columnconfigure(1, weight=1)
        self.detail_frame.grid_rowconfigure(0, weight=0)
        self.detail_frame.grid_rowconfigure(1, weight=1)

        media_wrap = ctk.CTkFrame(
            content_row,
            fg_color=("gray90", "gray15"),
            width=MEDIA_SIZE,
            height=MEDIA_SIZE,
            corner_radius=12,
        )
        media_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16))
        media_wrap.grid_propagate(False)

        self.media_label = ctk.CTkLabel(
            media_wrap,
            text="",
            width=MEDIA_SIZE,
            height=MEDIA_SIZE,
            fg_color="transparent",
        )
        self.media_label.place(relx=0.5, rely=0.5, anchor="center")
        self.media_label.bind("<Button-1>", lambda _event: self._open_current_media())
        media_wrap.bind("<Button-1>", lambda _event: self._open_current_media())
        media_wrap.configure(cursor="hand2")
        self.media_label.configure(cursor="hand2")

        media_controls = ctk.CTkFrame(content_row, fg_color="transparent", width=MEDIA_SIZE)
        media_controls.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        media_controls.grid_columnconfigure((0, 1, 2), weight=1)

        self.media_prev_button = ctk.CTkButton(
            media_controls,
            text="◀",
            width=36,
            height=32,
            command=self._prev_media,
        )
        self.media_prev_button.grid(row=0, column=0, sticky="e", padx=(0, 8))

        self.media_info_label = ctk.CTkLabel(
            media_controls,
            text="—",
            font=ctk.CTkFont(size=13),
            text_color=("gray30", "gray70"),
        )
        self.media_info_label.grid(row=0, column=1)

        self.media_next_button = ctk.CTkButton(
            media_controls,
            text="▶",
            width=36,
            height=32,
            command=self._next_media,
        )
        self.media_next_button.grid(row=0, column=2, sticky="w", padx=(8, 0))

        info_wrap = ctk.CTkFrame(content_row, fg_color="transparent")
        info_wrap.grid(row=0, column=1, sticky="nsew")
        info_wrap.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            info_wrap,
            text="",
            font=ctk.CTkFont(size=24, weight="bold"),
            anchor="w",
            justify="left",
        )
        self.title_label.grid(row=0, column=0, sticky="ew", pady=(8, 4))

        reaction_header = ctk.CTkFrame(info_wrap, fg_color="transparent")
        reaction_header.grid(row=1, column=0, sticky="w", pady=(8, 4))

        self.reaction_icon_label = ctk.CTkLabel(
            reaction_header,
            text="",
            width=36,
            height=36,
        )
        self.reaction_icon_label.pack(side="left", padx=(0, 8))

        self.status_label = ctk.CTkLabel(
            reaction_header,
            text="Реакция",
            anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        self.status_label.pack(side="left")

        self.reactions_box = ctk.CTkTextbox(
            info_wrap,
            wrap="word",
            font=ctk.CTkFont(size=14),
            height=90,
            text_color=("#1f538d", "#6fb0ff"),
        )
        self.reactions_box.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.reactions_box.configure(state="disabled")

        self.description_box = ctk.CTkTextbox(
            self.detail_frame,
            wrap="word",
            font=ctk.CTkFont(size=15),
            height=220,
        )
        self.description_box.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.description_box.configure(state="disabled")

        self.empty_label = ctk.CTkLabel(
            self.detail_frame,
            text="",
            text_color=("gray35", "gray70"),
        )
        self.empty_label.grid(row=2, column=0, sticky="w", pady=(6, 0))

    def _sidebar_entry(
        self,
        parent: ctk.CTkScrollableFrame,
        index: int,
        label: str,
        *,
        digits_only: bool = False,
    ) -> ctk.CTkEntry:
        row = index * 2
        ctk.CTkLabel(parent, text=label, anchor="w").grid(
            row=row, column=0, sticky="ew", padx=4, pady=(8, 4)
        )
        kwargs = {}
        if digits_only:
            kwargs["validate"] = "key"
            kwargs["validatecommand"] = self._age_validate
        entry = ctk.CTkEntry(parent, **kwargs)
        entry.grid(row=row + 1, column=0, sticky="ew", padx=4, pady=(0, 4))
        return entry

    def _sidebar_option(
        self,
        parent: ctk.CTkScrollableFrame,
        index: int,
        label: str,
        values: list[str],
    ) -> ctk.CTkOptionMenu:
        row = index * 2
        ctk.CTkLabel(parent, text=label, anchor="w").grid(
            row=row, column=0, sticky="ew", padx=4, pady=(8, 4)
        )
        option = ctk.CTkOptionMenu(parent, values=values, width=240)
        option.set(values[0])
        option.grid(row=row + 1, column=0, sticky="ew", padx=4, pady=(0, 4))
        return option

    def _bind_navigation_keys(self) -> None:
        bindings = (
            ("<Button-4>", self._go_back),
            ("<Button-5>", self._go_forward),
            ("<Alt-Left>", self._go_back),
            ("<Alt-Right>", self._go_forward),
        )
        for sequence, handler in bindings:
            self._safe_bind_all(sequence, handler)

        # XButton1/XButton2 работают не на всех платформах (Windows часто падает).
        for sequence, handler in (
            ("<XButton1>", self._go_back),
            ("<XButton2>", self._go_forward),
        ):
            self._safe_bind_all(sequence, handler)

    def _safe_bind_all(self, sequence: str, handler) -> None:
        try:
            self.bind_all(sequence, handler)
        except tk.TclError:
            pass

    def _navigation_snapshot(self) -> dict:
        return {
            "view": self.current_view,
            "profile_ids": list(self.profile_ids),
            "profile_summaries": list(self.profile_summaries),
            "current_index": self.current_index,
            "current_media_index": self.current_media_index,
        }

    def _restore_navigation_snapshot(self, state: dict) -> None:
        self.profile_ids = list(state["profile_ids"])
        self.profile_summaries = list(state["profile_summaries"])
        self.current_index = state["current_index"]
        self.current_media_index = state.get("current_media_index", 0)

        view = state["view"]
        if view == "home":
            self._show_home(record_history=False)
        elif view == "list":
            self._show_list(record_history=False)
        else:
            self._show_detail(record_history=False)

    def _go_back(self, _event=None) -> None:
        if self._nav_back:
            self._nav_forward.append(self._navigation_snapshot())
            self._restore_navigation_snapshot(self._nav_back.pop())
            return
        if self.current_view == "detail":
            self._show_list(record_history=False)
        elif self.current_view == "list":
            self._show_home(record_history=False)

    def _go_forward(self, _event=None) -> None:
        if not self._nav_forward:
            return
        self._nav_back.append(self._navigation_snapshot())
        self._restore_navigation_snapshot(self._nav_forward.pop())

    def _update_header(self) -> None:
        if self.current_view == "home":
            self.page_title.configure(text="Главная")
            self.header_info_label.configure(text="")
        elif self.current_view == "list":
            self.page_title.configure(text="Список анкет")
            self.header_info_label.configure(
                text=f"  ·  Найдено: {len(self.profile_summaries)}"
            )
        elif self.current_view == "detail":
            self.page_title.configure(text="Просмотр анкеты")
            total = len(self.profile_ids)
            if total:
                profile_id = self.profile_ids[self.current_index]
                info = f"  ·  #{profile_id}  ·  Анкета {self.current_index + 1} из {total}"
            else:
                info = ""
            self.header_info_label.configure(text=info)

        can_back = bool(self._nav_back) or self.current_view in {"list", "detail"}
        self.nav_back_button.configure(state="normal" if can_back else "disabled")
        self.nav_forward_button.configure(
            state="normal" if self._nav_forward else "disabled"
        )
        self._update_profile_nav_buttons()

    def _update_profile_nav_buttons(self) -> None:
        if self.current_view == "detail" and self.profile_ids:
            total = len(self.profile_ids)
            self.profile_prev_button.pack(side="left", padx=(0, 8))
            self.profile_next_button.pack(side="left")
            self.profile_prev_button.configure(
                state="normal" if self.current_index > 0 else "disabled"
            )
            self.profile_next_button.configure(
                state="normal" if self.current_index < total - 1 else "disabled"
            )
        else:
            self.profile_prev_button.pack_forget()
            self.profile_next_button.pack_forget()

    def _set_view(self, view: str) -> None:
        self.current_view = view
        self._update_header()

    def _validate_digits(self, value: str) -> bool:
        return value == "" or value.isdigit()

    def _load_city_options(self) -> None:
        cities = ["— любой —", *self.repo.get_cities()]
        self.city_option.configure(values=cities)
        self.city_option.set("— любой —")

    def _reset_filters(self) -> None:
        self.keyword_entry.delete(0, "end")
        self.city_option.set("— любой —")
        self.age_from_entry.delete(0, "end")
        self.age_from_entry.insert(0, "18")
        self.age_to_entry.delete(0, "end")
        self.age_to_entry.insert(0, "99")
        self.reaction_option.set("Все")
        self.period_option.set("За всё время")
        self._show_home(record_history=False)

    def _collect_filters(self) -> FilterParams:
        age_from = self._parse_age(self.age_from_entry.get(), 18)
        age_to = self._parse_age(self.age_to_entry.get(), 99)
        if age_from > age_to:
            age_from, age_to = age_to, age_from

        return FilterParams(
            keyword=self.keyword_entry.get(),
            city=self.city_option.get(),
            age_from=age_from,
            age_to=age_to,
            reaction=REACTION_OPTIONS[self.reaction_option.get()],
            period=PERIOD_OPTIONS[self.period_option.get()],
        )

    def _parse_age(self, value: str, default: int) -> int:
        value = value.strip()
        return int(value) if value else default

    def _hide_pages(self) -> None:
        for frame in (self.home_frame, self.list_frame, self.detail_frame):
            frame.grid_remove()

    def _render_latest_profiles(self) -> None:
        for child in self.latest_profiles_frame.winfo_children():
            child.destroy()

        latest = self.repo.get_latest_profiles(limit=8)
        if not latest:
            ctk.CTkLabel(
                self.latest_profiles_frame,
                text="Анкет пока нет",
                text_color=("gray35", "gray70"),
            ).grid(row=0, column=0, sticky="w", pady=4)
            return

        for index, summary in enumerate(latest):
            title = self._summary_title(summary)
            ctk.CTkButton(
                self.latest_profiles_frame,
                text=f"{title}    {summary.reaction_label}",
                anchor="w",
                fg_color=("gray82", "gray20"),
                hover_color=("gray70", "gray28"),
                command=lambda profile_id=summary.id: self._open_profile_by_id(profile_id),
            ).grid(row=index, column=0, sticky="ew", pady=3)

    def _show_home(self, *, record_history: bool = True) -> None:
        if record_history and self.current_view not in {"home", ""}:
            self._nav_back.append(self._navigation_snapshot())
            self._nav_forward.clear()

        stats = self.repo.get_stats()
        for key, label in self.stat_labels.items():
            label.configure(text=str(getattr(stats, key)))
        self._render_latest_profiles()
        self._hide_pages()
        self.home_frame.grid(row=0, column=0, sticky="nsew")
        self._set_view("home")

    def _apply_filters(self) -> None:
        if self.current_view != "list":
            self._nav_back.append(self._navigation_snapshot())
            self._nav_forward.clear()

        filters = self._collect_filters()
        self.profile_summaries = self.repo.search_profile_summaries(filters)
        self.profile_ids = [item.id for item in self.profile_summaries]
        self.current_index = 0
        self._show_list(record_history=False)

    def _show_list(self, *, record_history: bool = True) -> None:
        if record_history and self.current_view not in {"list", ""}:
            self._nav_back.append(self._navigation_snapshot())
            self._nav_forward.clear()

        self._hide_pages()
        self.list_frame.grid(row=0, column=0, sticky="nsew")
        self._set_view("list")
        self._render_list()

    def _render_list(self) -> None:
        for child in self.list_scroll.winfo_children():
            child.destroy()

        total = len(self.profile_summaries)
        self._update_header()

        if total == 0:
            self.list_empty_label.configure(
                text="Ничего не найдено, измените параметры поиска"
            )
            self.list_empty_label.grid(row=1, column=0, sticky="w", pady=8)
            return

        self.list_empty_label.grid_remove()

        for index, summary in enumerate(self.profile_summaries):
            title = self._summary_title(summary)
            row = ctk.CTkFrame(self.list_scroll)
            row.grid(row=index, column=0, sticky="ew", pady=4)
            row.grid_columnconfigure(0, weight=1)

            ctk.CTkButton(
                row,
                text=f"{title}    {summary.reaction_label}",
                anchor="w",
                fg_color=("gray82", "gray20"),
                hover_color=("gray70", "gray28"),
                command=lambda idx=index: self._open_profile(idx),
            ).grid(row=0, column=0, sticky="ew", padx=4, pady=4)

    def _summary_title(self, summary: ProfileSummary) -> str:
        return build_summary_title(summary)

    def _set_reactions_text(self, text: str) -> None:
        self.reactions_box.configure(state="normal")
        self.reactions_box.delete("1.0", "end")
        self.reactions_box.insert("1.0", text)
        self.reactions_box.configure(state="disabled")

    def _render_reaction_display(self, profile) -> None:
        if profile.mutual_like:
            icon_key = "mutual"
        elif profile.reactions:
            last = profile.reactions[-1]
            icon_key = reaction_icon_key(last.reaction_type, last.comment_text)
        else:
            icon_key = None

        icon = self._reaction_icons.get(icon_key) if icon_key else None
        if icon:
            self.reaction_icon_label.configure(image=icon, text="")
        else:
            self.reaction_icon_label.configure(image=None, text="—")

        text = format_reaction_status(profile)
        self._set_reactions_text(text)
        if profile.mutual_like:
            self.status_label.configure(text="Реакция · взаимный лайк")
        elif profile.reactions:
            self.status_label.configure(text="Реакция")
        else:
            self.status_label.configure(text="Реакция")

    def _open_profile_by_id(self, profile_id: int) -> None:
        if self.current_view != "detail":
            self._nav_back.append(self._navigation_snapshot())
            self._nav_forward.clear()

        latest = self.repo.get_latest_profiles(limit=8)
        self.profile_ids = [item.id for item in latest]
        if profile_id in self.profile_ids:
            self.current_index = self.profile_ids.index(profile_id)
        else:
            self.profile_ids = [profile_id]
            self.current_index = 0
        self.current_media_index = 0
        self._show_detail(record_history=False)

    def _open_profile(self, index: int) -> None:
        if self.current_view != "detail":
            self._nav_back.append(self._navigation_snapshot())
            self._nav_forward.clear()
        self.current_index = index
        self.current_media_index = 0
        self._show_detail(record_history=False)

    def _show_detail(self, *, record_history: bool = True) -> None:
        if record_history and self.current_view not in {"detail", ""}:
            self._nav_back.append(self._navigation_snapshot())
            self._nav_forward.clear()

        if not self.profile_ids:
            self._show_list(record_history=False)
            return

        self._hide_pages()
        self.detail_frame.grid(row=0, column=0, sticky="nsew")
        self._set_view("detail")
        self._render_current_profile()

    def _refresh_current_view(self) -> None:
        if self.current_view == "list":
            self._apply_filters()
        elif self.current_view == "detail":
            if self.profile_ids:
                filters = self._collect_filters()
                self.profile_summaries = self.repo.search_profile_summaries(filters)
                self.profile_ids = [item.id for item in self.profile_summaries]
                if self.current_index >= len(self.profile_ids):
                    self.current_index = max(0, len(self.profile_ids) - 1)
            self._render_current_profile()
        else:
            self._show_home()

    def _show_previous(self) -> None:
        if not self.profile_ids:
            return
        self.current_index = max(0, self.current_index - 1)
        self.current_media_index = 0
        self._render_current_profile()

    def _show_next(self) -> None:
        if not self.profile_ids:
            return
        self.current_index = min(len(self.profile_ids) - 1, self.current_index + 1)
        self.current_media_index = 0
        self._render_current_profile()

    def _render_current_profile(self) -> None:
        if not self.profile_ids:
            self._clear_profile_view("Ничего не найдено, измените параметры поиска")
            return

        profile_id = self.profile_ids[self.current_index]
        profile = self.repo.get_profile(profile_id)
        if profile is None:
            self._clear_profile_view("Анкета не найдена в базе данных")
            return

        total = len(self.profile_ids)
        self._update_header()
        self.empty_label.configure(text="")
        self.title_label.configure(text=build_title(profile))
        self._render_reaction_display(profile)

        self.description_box.configure(state="normal")
        self.description_box.delete("1.0", "end")
        self.description_box.insert("1.0", build_description(profile))
        self.description_box.configure(state="disabled")

        self.current_media_paths = collect_resolved_media(
            profile.media,
            self.settings.base_dir,
        )
        if self.current_media_index >= len(self.current_media_paths):
            self.current_media_index = 0
        self._render_current_media()
        self._update_profile_nav_buttons()

    def _clear_profile_view(self, message: str) -> None:
        self._release_image()
        self.media_label.configure(image=None, text=message)
        self.title_label.configure(text="")
        self.reaction_icon_label.configure(image=None, text="")
        self._set_reactions_text("")
        self.media_info_label.configure(text="—")
        self.description_box.configure(state="normal")
        self.description_box.delete("1.0", "end")
        self.description_box.insert("1.0", message)
        self.description_box.configure(state="disabled")
        self.header_info_label.configure(text="Анкета 0 из 0")
        self.empty_label.configure(text=message)
        self._update_profile_nav_buttons()
        self.media_prev_button.configure(state="disabled")
        self.media_next_button.configure(state="disabled")

    def _release_image(self) -> None:
        self.media_label.configure(image=None)
        self._ctk_image = None
        self._pil_image = None

    def _render_current_media(self) -> None:
        if not self.current_media_paths:
            self._release_image()
            self.media_label.configure(text="Медиа отсутствует")
            self.media_info_label.configure(text="—")
            self.media_prev_button.configure(state="disabled")
            self.media_next_button.configure(state="disabled")
            return

        item = self.current_media_paths[self.current_media_index]
        total = len(self.current_media_paths)

        try:
            pil_image = load_display_image(item.path)
            self._pil_image = pil_image
            display_w, display_h = pil_image.size
            self._ctk_image = ctk.CTkImage(
                light_image=pil_image,
                dark_image=pil_image,
                size=(display_w, display_h),
            )
            self.media_label.configure(image=self._ctk_image, text="")
            self.update_idletasks()
        except OSError:
            self._release_image()
            self.media_label.configure(text="Не удалось загрузить медиа")

        self.media_info_label.configure(
            text=media_caption(item, self.current_media_index, total)
        )
        self.media_prev_button.configure(
            state="normal" if self.current_media_index > 0 else "disabled"
        )
        self.media_next_button.configure(
            state="normal" if self.current_media_index < total - 1 else "disabled"
        )

    def _prev_media(self) -> None:
        if self.current_media_index > 0:
            self.current_media_index -= 1
            self._render_current_media()

    def _next_media(self) -> None:
        if self.current_media_index < len(self.current_media_paths) - 1:
            self.current_media_index += 1
            self._render_current_media()

    def _open_current_media(self) -> None:
        if not self.current_media_paths:
            return
        open_media_externally(self.current_media_paths[self.current_media_index].path)


def run_app(settings: ViewerSettings | None = None) -> None:
    app_settings = settings or load_viewer_settings()
    if not app_settings.db_path.is_file():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "База данных не найдена",
            f"Файл не найден:\n{app_settings.db_path}\n\n"
            "Сначала запустите userbot и соберите анкеты.",
        )
        root.destroy()
        return

    app = ProfileViewerApp(app_settings)
    app.mainloop()
