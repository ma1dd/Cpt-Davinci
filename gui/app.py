import re
import tkinter as tk
import threading
from collections.abc import Callable
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image

from database.viewer_queries import (
    FilterParams,
    PeriodFilter,
    ProfileSummary,
    ProfileView,
    ProfileViewerRepository,
    ReactionFilter,
    build_description,
    build_summary_title,
    build_title,
    format_reaction_messages,
    reaction_kind,
)
from services.trash_analyzer import format_trash_percent
from gui.emoji_text import (
    TEXT_FONT_DESCRIPTION,
    TEXT_FONT_REACTION,
    configure_copyable_readonly,
    emoji_to_ctk_image,
    emoji_ui_font,
    estimate_textbox_height,
    plain_ui_font,
    populate_emoji_textbox,
    populate_trash_summary_colored,
    populate_trash_tag_panels,
)
from gui.incremental_list import IncrementalProfileList
from gui.profile_row import populate_profile_rows
from gui.reaction_picker import ReactionPicker
from gui.trash_gauge import TrashOver90Gauge
from gui.media import (
    MEDIA_SIZE,
    collect_resolved_media,
    load_display_image,
    media_caption,
    open_media_externally,
)
from viewer_config import ViewerSettings, load_viewer_settings

SIDEBAR_WIDTH = 310
AGE_MIN = 18
AGE_MAX = 99
PROFILE_CACHE_SIZE = 80
IMAGE_CACHE_SIZE = 48
LIST_LOAD_DEBOUNCE_MS = 50
REACTION_KIND_EMOJI = {
    "mutual": "💞",
    "like": "❤️",
    "dislike": "👎",
    "message": "💬",
    "none": "❌",
}
REACTION_OPTIONS = {
    "Все": ReactionFilter.ALL,
    "❤️ Лайк": ReactionFilter.LIKE,
    "👎 Дизлайк": ReactionFilter.DISLIKE,
    "💬 С комментарием": ReactionFilter.COMMENT,
    "💞 Взаимные лайки": ReactionFilter.MUTUAL,
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
        self._reaction_emoji_img: ctk.CTkImage | None = None
        self._trash_backfill_running = False
        self._profile_cache: dict[int, ProfileView] = {}
        self._image_cache: dict[str, ctk.CTkImage] = {}
        self._toggle_filter_sections: dict[str, dict] = {}
        self._list_load_generation = 0

        self._build_layout()
        self._bind_navigation_keys()
        self._load_city_options()
        self.after(100, self._warm_emoji_cache)
        self.after(2500, self._start_trash_backfill)
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
        self.filters_scroll = scroll

        filter_row = 0
        self.keyword_entry = self._sidebar_entry(
            scroll,
            filter_row,
            "Поиск по описанию (!123 — по номеру)",
        )
        filter_row += 1
        self.city_option = self._sidebar_toggle_option(
            scroll,
            filter_row,
            "Город",
            ["— любой —"],
        )
        filter_row += 1
        self._build_age_filter(scroll, filter_row)
        filter_row += 1
        self.min_words_entry = self._sidebar_entry(
            scroll,
            filter_row,
            "Слов в описании, больше чем",
        )
        self.min_words_entry.insert(0, "0")
        filter_row += 1
        self.reaction_option = self._sidebar_toggle_reaction_picker(
            scroll,
            filter_row,
            "Реакция",
            list(REACTION_OPTIONS.keys()),
        )
        filter_row += 1
        self.period_option = self._sidebar_option(
            scroll,
            filter_row,
            "Период",
            list(PERIOD_OPTIONS.keys()),
        )
        filter_row += 1

        self.keyword_entry.bind("<Return>", lambda _event: self._apply_filters())

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
        self.content.grid_rowconfigure(2, weight=0)

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
        self.refresh_button.grid(row=0, column=0, padx=(0, 8))

        self.nav_back_button = ctk.CTkButton(
            nav_wrap,
            text="◀ Назад",
            width=90,
            command=self._go_back,
        )
        self.nav_back_button.grid(row=0, column=1, padx=(0, 8))

        self.nav_forward_button = ctk.CTkButton(
            nav_wrap,
            text="Вперёд ▶",
            width=90,
            command=self._go_forward,
        )
        self.nav_forward_button.grid(row=0, column=2)

        self.body = ctk.CTkFrame(self.content, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 4))
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)

        self.footer = ctk.CTkFrame(self.content, fg_color="transparent")
        self.footer.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 4))
        self.footer.grid_columnconfigure(1, weight=1)
        self.footer.grid_remove()

        profile_nav = ctk.CTkFrame(self.footer, fg_color="transparent")
        profile_nav.grid(row=0, column=2, sticky="e")

        self.profile_prev_button = ctk.CTkButton(
            profile_nav,
            text="◀ Пред.",
            width=90,
            command=self._show_previous,
        )
        self.profile_prev_button.grid(row=0, column=0, padx=(0, 8))

        self.profile_next_button = ctk.CTkButton(
            profile_nav,
            text="След. ▶",
            width=90,
            command=self._show_next,
        )
        self.profile_next_button.grid(row=0, column=1)

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
        wrap = ctk.CTkFrame(self.home_frame, fg_color="transparent")
        wrap.grid(row=0, column=0, sticky="nsew")
        wrap.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.stat_labels: dict[str, ctk.CTkLabel] = {}
        cards = [
            ("profiles", "Анкет"),
            ("likes", "Лайков"),
            ("dislikes", "Дизлайков"),
            ("comments", "Коммент."),
            ("mutual_likes", "Взаимн."),
            ("avg_trash_score", "Ср. мусор"),
        ]
        for index, (key, title) in enumerate(cards):
            card = ctk.CTkFrame(wrap, corner_radius=10)
            card.grid(
                row=index // 4,
                column=index % 4,
                sticky="nsew",
                padx=6,
                pady=6,
            )
            ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=12)).pack(
                anchor="w", padx=10, pady=(10, 0)
            )
            value_label = ctk.CTkLabel(
                card, text="0", font=ctk.CTkFont(size=22, weight="bold")
            )
            value_label.pack(anchor="w", padx=10, pady=(0, 10))
            self.stat_labels[key] = value_label

        gauge_card = ctk.CTkFrame(wrap, corner_radius=10)
        gauge_card.grid(row=1, column=2, columnspan=2, sticky="nsew", padx=6, pady=6)
        ctk.CTkLabel(
            gauge_card,
            text="Мусор > 90%",
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=10, pady=(10, 0))
        self.trash_over_90_gauge = TrashOver90Gauge(gauge_card, size=88)
        self.trash_over_90_gauge.pack(padx=10, pady=(4, 10), anchor="w")

        latest_header = ctk.CTkFrame(wrap, fg_color="transparent")
        latest_header.grid(row=2, column=0, columnspan=4, sticky="ew", padx=8, pady=(12, 4))
        latest_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            latest_header,
            text="Последние анкеты",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            latest_header,
            text="Все анкеты",
            width=100,
            height=28,
            fg_color=("gray75", "gray25"),
            hover_color=("gray65", "gray35"),
            command=self._open_all_profiles_list,
        ).grid(row=0, column=1, sticky="e")

        self.latest_profiles_frame = ctk.CTkFrame(wrap, fg_color="transparent")
        self.latest_profiles_frame.grid(
            row=3, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 8)
        )
        self.latest_profiles_frame.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(3, weight=0)

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
        self.list_loading_label = ctk.CTkLabel(
            self.list_frame,
            text="Загрузка…",
            text_color=("gray35", "gray70"),
        )
        self._profile_list = IncrementalProfileList(self.list_scroll)

    def _build_detail_page(self) -> None:
        self.detail_frame.grid_rowconfigure(0, weight=0)
        self.detail_frame.grid_rowconfigure(1, weight=1)
        self.detail_frame.grid_columnconfigure(0, weight=1)

        content_row = ctk.CTkFrame(self.detail_frame, fg_color="transparent")
        content_row.grid(row=0, column=0, sticky="ew")
        content_row.grid_columnconfigure(1, weight=1)

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

        self.media_controls = ctk.CTkFrame(content_row, fg_color="transparent", width=MEDIA_SIZE)
        self.media_controls.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.media_controls.grid_columnconfigure((0, 1, 2), weight=1)

        self.media_prev_button = ctk.CTkButton(
            self.media_controls,
            text="◀",
            width=36,
            height=32,
            command=self._prev_media,
        )
        self.media_prev_button.grid(row=0, column=0, sticky="e", padx=(0, 8))

        self.media_info_label = ctk.CTkLabel(
            self.media_controls,
            text="—",
            font=ctk.CTkFont(size=13),
            text_color=("gray30", "gray70"),
        )
        self.media_info_label.grid(row=0, column=1)

        self.media_next_button = ctk.CTkButton(
            self.media_controls,
            text="▶",
            width=36,
            height=32,
            command=self._next_media,
        )
        self.media_next_button.grid(row=0, column=2, sticky="w", padx=(8, 0))

        info_wrap = ctk.CTkFrame(content_row, fg_color="transparent")
        info_wrap.grid(row=0, column=1, rowspan=2, sticky="nsew")
        info_wrap.grid_columnconfigure(0, weight=1)
        info_wrap.grid_rowconfigure(3, weight=1)

        self.title_label = ctk.CTkLabel(
            info_wrap,
            text="",
            font=ctk.CTkFont(size=24, weight="bold"),
            anchor="w",
            justify="left",
        )
        self.title_label.grid(row=0, column=0, sticky="ew", pady=(8, 4))

        reaction_header = ctk.CTkFrame(info_wrap, fg_color="transparent")
        reaction_header.grid(row=1, column=0, sticky="w", pady=(4, 4))

        self.reaction_emoji_label = ctk.CTkLabel(
            reaction_header,
            text="",
            width=28,
            height=28,
        )
        self.reaction_emoji_label.pack(side="left", padx=(0, 8))

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
            font=plain_ui_font(TEXT_FONT_REACTION),
            height=36,
            text_color=("#1f538d", "#6fb0ff"),
        )
        self.reactions_box.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        self.reactions_box.grid_remove()

        self.trash_block = ctk.CTkFrame(
            info_wrap,
            fg_color=("gray88", "gray18"),
            corner_radius=10,
            border_width=1,
            border_color=("gray75", "gray28"),
        )
        self.trash_block.grid(row=3, column=0, sticky="nsew", pady=(4, 0))
        self.trash_block.grid_columnconfigure((0, 1), weight=1)
        self.trash_block.grid_rowconfigure(1, weight=1)

        self.trash_summary_box = ctk.CTkTextbox(
            self.trash_block,
            wrap="word",
            font=plain_ui_font(14),
            height=34,
        )
        self.trash_summary_box.grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 6),
        )

        tags_row = ctk.CTkFrame(self.trash_block, fg_color="transparent")
        tags_row.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10))
        tags_row.grid_columnconfigure((0, 1), weight=1)
        tags_row.grid_rowconfigure(0, weight=1)

        self.trash_minus_box = ctk.CTkTextbox(
            tags_row,
            wrap="word",
            font=plain_ui_font(12),
            height=96,
        )
        self.trash_minus_box.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        self.trash_plus_box = ctk.CTkTextbox(
            tags_row,
            wrap="word",
            font=plain_ui_font(12),
            height=96,
        )
        self.trash_plus_box.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        self.description_box = ctk.CTkTextbox(
            self.detail_frame,
            wrap="word",
            font=plain_ui_font(TEXT_FONT_DESCRIPTION),
            height=220,
        )
        self.description_box.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        self.empty_label = ctk.CTkLabel(
            self.detail_frame,
            text="",
            text_color=("gray35", "gray70"),
        )
        self.empty_label.grid(row=2, column=0, sticky="w", pady=(4, 0))

    def _sidebar_toggle_option(
        self,
        parent: ctk.CTkScrollableFrame,
        index: int,
        label: str,
        values: list[str],
        *,
        emoji_font: bool = False,
        option_font: ctk.CTkFont | None = None,
    ) -> ctk.CTkOptionMenu:
        row = index * 2
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=row, column=0, sticky="ew", padx=4, pady=(8, 4))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text=label, anchor="w").grid(row=0, column=0, sticky="w")

        toggle = ctk.CTkButton(
            header,
            text="▼",
            width=28,
            height=22,
            fg_color=("gray78", "gray22"),
            hover_color=("gray70", "gray28"),
            command=lambda title=label: self._toggle_filter_option(title),
        )
        toggle.grid(row=0, column=1, sticky="e")

        body = ctk.CTkFrame(parent, fg_color="transparent")
        body.grid(row=row + 1, column=0, sticky="ew", padx=4, pady=(0, 4))
        body.grid_columnconfigure(0, weight=1)

        font = option_font or (emoji_ui_font(13) if emoji_font else ctk.CTkFont(size=13))
        option = ctk.CTkOptionMenu(
            body,
            values=values,
            width=240,
            font=font,
            dropdown_font=font,
        )
        option.set(values[0])
        option.pack(fill="x")

        self._toggle_filter_sections[label] = {
            "open": True,
            "toggle": toggle,
            "body": body,
        }
        return option

    def _sidebar_toggle_reaction_picker(
        self,
        parent: ctk.CTkScrollableFrame,
        index: int,
        label: str,
        values: list[str],
    ) -> ReactionPicker:
        row = index * 2
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=row, column=0, sticky="ew", padx=4, pady=(8, 4))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text=label, anchor="w").grid(row=0, column=0, sticky="w")

        toggle = ctk.CTkButton(
            header,
            text="▼",
            width=28,
            height=22,
            fg_color=("gray78", "gray22"),
            hover_color=("gray70", "gray28"),
            command=lambda title=label: self._toggle_filter_option(title),
        )
        toggle.grid(row=0, column=1, sticky="e")

        body = ctk.CTkFrame(parent, fg_color="transparent")
        body.grid(row=row + 1, column=0, sticky="ew", padx=4, pady=(0, 4))
        body.grid_columnconfigure(0, weight=1)

        picker = ReactionPicker(body, labels=values, width=240)
        picker.pack(fill="x")

        self._toggle_filter_sections[label] = {
            "open": True,
            "toggle": toggle,
            "body": body,
        }
        return picker

    def _toggle_filter_option(self, title: str) -> None:
        section = self._toggle_filter_sections.get(title)
        if not section:
            return
        section["open"] = not section["open"]
        if section["open"]:
            section["body"].grid()
            section["toggle"].configure(text="▼")
        else:
            section["body"].grid_remove()
            section["toggle"].configure(text="▶")

    def _sidebar_entry(
        self,
        parent: ctk.CTkScrollableFrame,
        index: int,
        label: str,
    ) -> ctk.CTkEntry:
        row = index * 2
        ctk.CTkLabel(parent, text=label, anchor="w").grid(
            row=row, column=0, sticky="ew", padx=4, pady=(8, 4)
        )
        entry = ctk.CTkEntry(parent)
        entry.grid(row=row + 1, column=0, sticky="ew", padx=4, pady=(0, 4))
        return entry

    def _sidebar_option(
        self,
        parent: ctk.CTkScrollableFrame,
        index: int,
        label: str,
        values: list[str],
        *,
        emoji_font: bool = False,
    ) -> ctk.CTkOptionMenu:
        row = index * 2
        ctk.CTkLabel(parent, text=label, anchor="w").grid(
            row=row, column=0, sticky="ew", padx=4, pady=(8, 4)
        )
        font = emoji_ui_font(13) if emoji_font else ctk.CTkFont(size=13)
        option = ctk.CTkOptionMenu(
            parent,
            values=values,
            width=240,
            font=font,
            dropdown_font=font,
        )
        option.set(values[0])
        option.grid(row=row + 1, column=0, sticky="ew", padx=4, pady=(0, 4))
        return option

    def _build_age_filter(self, parent: ctk.CTkScrollableFrame, index: int) -> None:
        row = index * 2
        ctk.CTkLabel(parent, text="Возраст", anchor="w").grid(
            row=row, column=0, sticky="ew", padx=4, pady=(8, 4)
        )

        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid(row=row + 1, column=0, sticky="ew", padx=4, pady=(0, 4))
        wrap.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(wrap, text="от", width=22, anchor="w", font=plain_ui_font(12)).grid(
            row=0, column=0, sticky="w"
        )
        self.age_from_entry = ctk.CTkEntry(wrap, width=90)
        self.age_from_entry.grid(row=0, column=1, sticky="ew", padx=(4, 12))
        self.age_from_entry.insert(0, str(AGE_MIN))

        ctk.CTkLabel(wrap, text="до", width=22, anchor="w", font=plain_ui_font(12)).grid(
            row=0, column=2, sticky="w"
        )
        self.age_to_entry = ctk.CTkEntry(wrap, width=90)
        self.age_to_entry.grid(row=0, column=3, sticky="ew", padx=(4, 0))
        self.age_to_entry.insert(0, str(AGE_MAX))

    def _clear_profile_cache(self) -> None:
        self._profile_cache.clear()

    def _get_cached_profile(self, profile_id: int) -> ProfileView | None:
        if profile_id not in self._profile_cache:
            profile = self.repo.get_profile(profile_id)
            if profile is None:
                return None
            if len(self._profile_cache) >= PROFILE_CACHE_SIZE:
                self._profile_cache.pop(next(iter(self._profile_cache)))
            self._profile_cache[profile_id] = profile
        return self._profile_cache[profile_id]

    def _prefetch_neighbor_profiles(self) -> None:
        if not self.profile_ids or self.current_view != "detail":
            return
        neighbor_ids: list[int] = []
        if self.current_index > 0:
            neighbor_ids.append(self.profile_ids[self.current_index - 1])
        if self.current_index < len(self.profile_ids) - 1:
            neighbor_ids.append(self.profile_ids[self.current_index + 1])

        def worker() -> None:
            for profile_id in neighbor_ids:
                self._get_cached_profile(profile_id)

        threading.Thread(target=worker, daemon=True).start()

    def _load_cached_media_image(self, path) -> ctk.CTkImage:
        key = str(path.resolve())
        cached = self._image_cache.get(key)
        if cached is not None:
            return cached

        pil_image = load_display_image(path)
        display_w, display_h = pil_image.size
        ctk_image = ctk.CTkImage(
            light_image=pil_image,
            dark_image=pil_image,
            size=(display_w, display_h),
        )
        if len(self._image_cache) >= IMAGE_CACHE_SIZE:
            self._image_cache.pop(next(iter(self._image_cache)))
        self._image_cache[key] = ctk_image
        return ctk_image

    def _parse_age_entry(self, entry: ctk.CTkEntry, default: int) -> int:
        raw = entry.get().strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            return default
        return max(AGE_MIN, min(AGE_MAX, value))

    def _parse_min_words_entry(self) -> int:
        raw = self.min_words_entry.get().strip()
        if not raw:
            return 0
        try:
            value = int(raw)
        except ValueError:
            return 0
        return max(0, value)

    def _bind_navigation_keys(self) -> None:
        bindings = (
            ("<Button-4>", self._go_back),
            ("<Button-5>", self._go_forward),
            ("<Alt-Left>", self._go_back),
            ("<Alt-Right>", self._go_forward),
            ("<Left>", self._on_profile_left),
            ("<Right>", self._on_profile_right),
            ("<Up>", self._on_media_up),
            ("<Down>", self._on_media_down),
        )
        for sequence, handler in bindings:
            self._safe_bind_all(sequence, handler)

        for sequence, handler in (
            ("<XButton1>", self._go_back),
            ("<XButton2>", self._go_forward),
        ):
            self._safe_bind_all(sequence, handler)

    def _on_profile_left(self, _event=None) -> str | None:
        if self.current_view != "detail" or not self.profile_ids:
            return None
        if self.current_index <= 0:
            return None
        self._show_previous()
        return "break"

    def _on_profile_right(self, _event=None) -> str | None:
        if self.current_view != "detail" or not self.profile_ids:
            return None
        if self.current_index >= len(self.profile_ids) - 1:
            return None
        self._show_next()
        return "break"

    def _on_media_up(self, _event=None) -> str | None:
        if self.current_view != "detail" or not self.current_media_paths:
            return None
        self._prev_media()
        return "break"

    def _on_media_down(self, _event=None) -> str | None:
        if self.current_view != "detail" or not self.current_media_paths:
            return None
        self._next_media()
        return "break"

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
        on_detail = self.current_view == "detail" and bool(self.profile_ids)
        total = len(self.profile_ids) if on_detail else 0

        if on_detail:
            self.footer.grid()
            self.profile_prev_button.configure(
                state="normal" if self.current_index > 0 else "disabled"
            )
            self.profile_next_button.configure(
                state="normal" if self.current_index < total - 1 else "disabled"
            )
        else:
            self.footer.grid_remove()
            self.profile_prev_button.configure(state="disabled")
            self.profile_next_button.configure(state="disabled")

    def _set_view(self, view: str) -> None:
        self.current_view = view
        self._update_header()

    def _warm_emoji_cache(self) -> None:
        from gui.emoji_text import warm_emoji_cache

        warm_emoji_cache()

    def _load_city_options(self) -> None:
        cities = ["— любой —", *self.repo.get_cities()]
        self.city_option.configure(values=cities)
        self.city_option.set("— любой —")

    def _reset_filters(self) -> None:
        self.keyword_entry.delete(0, "end")
        self.city_option.set("— любой —")
        self.age_from_entry.delete(0, "end")
        self.age_from_entry.insert(0, str(AGE_MIN))
        self.age_to_entry.delete(0, "end")
        self.age_to_entry.insert(0, str(AGE_MAX))
        self.min_words_entry.delete(0, "end")
        self.min_words_entry.insert(0, "0")
        self.reaction_option.set("Все")
        self.period_option.set("За всё время")
        self._show_home(record_history=False)

    def _collect_filters(self) -> FilterParams:
        age_from = self._parse_age_entry(self.age_from_entry, AGE_MIN)
        age_to = self._parse_age_entry(self.age_to_entry, AGE_MAX)
        if age_from > age_to:
            age_from, age_to = age_to, age_from

        return FilterParams(
            keyword=self.keyword_entry.get(),
            city=self.city_option.get(),
            age_from=age_from,
            age_to=age_to,
            min_words=self._parse_min_words_entry(),
            reaction=REACTION_OPTIONS[self.reaction_option.get()],
            period=PERIOD_OPTIONS[self.period_option.get()],
        )

    def _hide_pages(self) -> None:
        for frame in (self.home_frame, self.list_frame, self.detail_frame):
            frame.grid_remove()

    def _profile_row_items_from_summaries(
        self,
        summaries: list[ProfileSummary],
        *,
        index_commands: bool,
    ) -> list[tuple[str, str, float | None, Callable[[], None]]]:
        items: list[tuple[str, str, float | None, Callable[[], None]]] = []
        for index, summary in enumerate(summaries):
            title = self._summary_title(summary)
            if index_commands:
                command = lambda idx=index: self._open_profile(idx)
            else:
                command = lambda profile_id=summary.id: self._open_profile_by_id(profile_id)
            items.append((title, summary.reaction_label, summary.trash_score, command))
        return items

    def _render_latest_profiles(self) -> None:
        latest = self.repo.get_latest_profiles(limit=5)
        if not latest:
            for child in self.latest_profiles_frame.winfo_children():
                child.destroy()
            ctk.CTkLabel(
                self.latest_profiles_frame,
                text="Анкет пока нет",
                text_color=("gray35", "gray70"),
            ).pack(anchor="w", pady=2)
            return

        populate_profile_rows(
            self.latest_profiles_frame,
            self._profile_row_items_from_summaries(latest, index_commands=False),
        )

    def _open_all_profiles_list(self) -> None:
        """Список всех анкет с пустыми фильтрами (как «Применить» без условий)."""
        if self.current_view not in {"home", ""}:
            self._nav_back.append(self._navigation_snapshot())
            self._nav_forward.clear()

        filters = FilterParams()
        self._clear_profile_cache()
        self.current_index = 0
        self._show_list(record_history=False, render=False)
        self._start_list_query(filters)

    def _refresh_home_stats(self) -> None:
        stats = self.repo.get_stats()
        for key, label in self.stat_labels.items():
            value = getattr(stats, key)
            if key == "avg_trash_score":
                label.configure(
                    text=format_trash_percent(value) if value is not None else "—"
                )
            else:
                label.configure(text=str(value))
        self.trash_over_90_gauge.set_value(stats.trash_over_90_pct)
        self._render_latest_profiles()

    def _start_list_query(self, filters: FilterParams) -> None:
        self._list_load_generation += 1
        generation = self._list_load_generation
        self.profile_summaries = []
        self.profile_ids = []
        self._profile_list.reset([])
        self.list_empty_label.grid_remove()
        self.list_loading_label.configure(text="Загрузка…")
        self.list_loading_label.grid(row=1, column=0, sticky="w", pady=8)
        self._update_header()

        def worker() -> None:
            summaries = self.repo.search_profile_summaries(filters)
            self.after(
                LIST_LOAD_DEBOUNCE_MS,
                lambda: self._finish_list_query(generation, summaries),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _finish_list_query(
        self,
        generation: int,
        summaries: list[ProfileSummary],
    ) -> None:
        if generation != self._list_load_generation or self.current_view != "list":
            return
        self.list_loading_label.grid_remove()
        self.profile_summaries = summaries
        self.profile_ids = [item.id for item in summaries]
        self._render_list()

    def _show_home(self, *, record_history: bool = True) -> None:
        if record_history and self.current_view not in {"home", ""}:
            self._nav_back.append(self._navigation_snapshot())
            self._nav_forward.clear()

        stats = self.repo.get_stats()
        for key, label in self.stat_labels.items():
            value = getattr(stats, key)
            if key == "avg_trash_score":
                label.configure(
                    text=format_trash_percent(value) if value is not None else "—"
                )
            else:
                label.configure(text=str(value))
        self.trash_over_90_gauge.set_value(stats.trash_over_90_pct)
        self._render_latest_profiles()
        self._hide_pages()
        self.home_frame.grid(row=0, column=0, sticky="nsew")
        self._set_view("home")

    def _apply_filters(self) -> None:
        keyword = self.keyword_entry.get().strip()
        if self._try_jump_to_profile_id(keyword):
            return

        if self.current_view != "list":
            self._nav_back.append(self._navigation_snapshot())
            self._nav_forward.clear()

        self._clear_profile_cache()
        filters = self._collect_filters()
        self.current_index = 0
        self._show_list(record_history=False, render=False)
        self._start_list_query(filters)

    def _try_jump_to_profile_id(self, keyword: str) -> bool:
        match = re.fullmatch(r"!\s*(\d+)", keyword)
        if not match:
            return False

        profile_id = int(match.group(1))
        if self.repo.get_profile(profile_id) is None:
            messagebox.showinfo(
                "Анкета не найдена",
                f"Анкета #{profile_id} не найдена в базе.",
            )
            return True

        if self.current_view != "detail":
            self._nav_back.append(self._navigation_snapshot())
            self._nav_forward.clear()

        self.profile_ids = [profile_id]
        self.current_index = 0
        self.current_media_index = 0
        self._show_detail(record_history=False)
        return True

    def _show_list(self, *, record_history: bool = True, render: bool = True) -> None:
        if record_history and self.current_view not in {"list", ""}:
            self._nav_back.append(self._navigation_snapshot())
            self._nav_forward.clear()

        self._hide_pages()
        self.list_frame.grid(row=0, column=0, sticky="nsew")
        self._set_view("list")
        if render:
            self._render_list()

    def _render_list(self) -> None:
        total = len(self.profile_summaries)
        self._update_header()

        if total == 0:
            self.list_loading_label.grid_remove()
            self._profile_list.reset([])
            self.list_empty_label.configure(
                text="Ничего не найдено, измените параметры поиска"
            )
            self.list_empty_label.grid(row=1, column=0, sticky="w", pady=8)
            return

        self.list_empty_label.grid_remove()
        self.list_loading_label.grid_remove()
        self._profile_list.reset(
            self._profile_row_items_from_summaries(
                self.profile_summaries,
                index_commands=True,
            )
        )

    def _summary_title(self, summary: ProfileSummary) -> str:
        return build_summary_title(summary)

    def _set_reactions_text(self, text: str) -> None:
        populate_emoji_textbox(self.reactions_box, text, font_size=TEXT_FONT_REACTION)

    def _reaction_box_height(self, text: str) -> int:
        return estimate_textbox_height(
            text, TEXT_FONT_REACTION, min_height=36, max_height=220
        )

    def _set_description_text(self, text: str) -> None:
        populate_emoji_textbox(self.description_box, text, font_size=TEXT_FONT_DESCRIPTION)

    def _set_reaction_emoji(self, kind: str | None) -> None:
        emoji_char = REACTION_KIND_EMOJI.get(kind or "none", "❌")
        image = emoji_to_ctk_image(emoji_char, size=22)
        self._reaction_emoji_img = image
        if image:
            self.reaction_emoji_label.configure(image=image, text="")
        else:
            self.reaction_emoji_label.configure(image=None, text=emoji_char)

    def _hide_reactions_box(self) -> None:
        self.reactions_box.grid_remove()

    def _show_reactions_box(self, text: str) -> None:
        self.reactions_box.configure(height=self._reaction_box_height(text))
        self._set_reactions_text(text)
        self.reactions_box.grid(row=2, column=0, sticky="ew", pady=(0, 8))

    def _render_reaction_display(self, profile) -> None:
        kind = reaction_kind(profile)

        if kind == "mutual":
            self.status_label.configure(text="Взаимный лайк")
            self._hide_reactions_box()
        elif kind == "like":
            self.status_label.configure(text="Лайк")
            self._hide_reactions_box()
        elif kind == "dislike":
            self.status_label.configure(text="Дизлайк")
            self._hide_reactions_box()
        elif kind == "message":
            self.status_label.configure(text="Реакция")
            self._show_reactions_box(format_reaction_messages(profile))
        else:
            self.status_label.configure(text="Реакция · ещё не поставлена")
            self._hide_reactions_box()

        self._set_reaction_emoji(kind or "none")

    def _set_trash_tags_text(self, tags) -> None:
        populate_trash_tag_panels(self.trash_minus_box, self.trash_plus_box, tags)

    def _clear_trash_tags(self) -> None:
        for box in (self.trash_minus_box, self.trash_plus_box):
            tw = box._textbox
            tw.configure(state="normal")
            tw.delete("1.0", "end")
            configure_copyable_readonly(box)

    def _set_trash_summary_text(self, text: str, *, score: float | None = None) -> None:
        populate_trash_summary_colored(
            self.trash_summary_box,
            text,
            score=score,
            font_size=14,
        )

    def _render_trash_display(self, profile: ProfileView) -> None:
        if profile.trash_score is None:
            self._set_trash_summary_text("Мусорность: ещё не рассчитана")
            self._clear_trash_tags()
            return

        score_text = format_trash_percent(profile.trash_score)
        label = profile.trash_label or ""
        self._set_trash_summary_text(
            f"Мусорность: {score_text} · {label}",
            score=profile.trash_score,
        )

        if profile.trash_tags:
            self._set_trash_tags_text(profile.trash_tags)
            minus_count = sum(1 for tag in profile.trash_tags if tag.delta < 0)
            plus_count = sum(1 for tag in profile.trash_tags if tag.delta >= 0)
            panel_height = min(
                160,
                max(72, 18 * max(minus_count, plus_count, 1) + 16),
            )
            self.trash_minus_box.configure(height=panel_height)
            self.trash_plus_box.configure(height=panel_height)
        else:
            self._clear_trash_tags()

    def _start_trash_backfill(self) -> None:
        if self._trash_backfill_running:
            return
        if self.repo.count_pending_trash_analysis() <= 0:
            return
        self._trash_backfill_running = True
        threading.Thread(target=self._run_trash_backfill_loop, daemon=True).start()

    def _run_trash_backfill_loop(self) -> None:
        while True:
            processed = self.repo.backfill_trash_analysis()
            if processed <= 0:
                break
        self._trash_backfill_running = False
        self.after(0, self._on_trash_backfill_done)

    def _on_trash_backfill_done(self) -> None:
        if self.current_view == "home":
            self._refresh_home_stats()
        elif self.current_view == "detail" and self.profile_ids:
            self._render_current_profile()

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
            self._clear_profile_cache()
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
        profile = self._get_cached_profile(profile_id)
        if profile is None:
            self._clear_profile_view("Анкета не найдена в базе данных")
            return

        total = len(self.profile_ids)
        self._update_header()
        self.empty_label.configure(text="")
        self.title_label.configure(text=build_title(profile))
        self._render_reaction_display(profile)
        self._render_trash_display(profile)

        self._set_description_text(build_description(profile))

        self.current_media_paths = collect_resolved_media(
            profile.media,
            self.settings.base_dir,
        )
        if self.current_media_index >= len(self.current_media_paths):
            self.current_media_index = 0
        self._render_current_media()
        self._update_profile_nav_buttons()
        self._prefetch_neighbor_profiles()

    def _clear_profile_view(self, message: str) -> None:
        self._release_image()
        self.media_label.configure(image=None, text=message)
        self.title_label.configure(text="")
        self._set_reaction_emoji("none")
        self.status_label.configure(text="Реакция · ещё не поставлена")
        self._hide_reactions_box()
        self.trash_summary_box.configure(height=34)
        self._set_trash_summary_text("")
        self._clear_trash_tags()
        self.trash_minus_box.configure(height=96)
        self.trash_plus_box.configure(height=96)
        self.media_info_label.configure(text="—")
        self._set_description_text(message)
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
            self.media_controls.grid_remove()
            return

        item = self.current_media_paths[self.current_media_index]
        total = len(self.current_media_paths)
        single_video = total == 1 and item.media_type in {"video", "animation"}

        try:
            self._ctk_image = self._load_cached_media_image(item.path)
            self.media_label.configure(image=self._ctk_image, text="")
            self.update_idletasks()
        except OSError:
            self._release_image()
            self.media_label.configure(text="Не удалось загрузить медиа")

        if single_video:
            self.media_controls.grid()
            self.media_info_label.configure(text="Видео · нажмите для просмотра")
            self.media_prev_button.configure(state="disabled")
            self.media_next_button.configure(state="disabled")
        else:
            self.media_controls.grid()
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
