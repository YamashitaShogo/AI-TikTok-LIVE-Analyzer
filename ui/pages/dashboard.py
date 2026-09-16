import json
import queue
import os
from pathlib import Path
from typing import Any, Optional

import customtkinter as ctk
from PIL import Image

from core.auto_analyzer import AutoAnalyzer
from core.history import HistoryDB
from core.settings import Settings


class DashboardPage(ctk.CTkFrame):
    """Livemetry Pulse ダッシュボード完成版。"""

    DEFAULT_INTERVAL = 30
    GRAPH_LIMIT = 20
    SCREENSHOT_REFRESH_MS = 3000
    DASHBOARD_REFRESH_MS = 5000

    def __init__(self, parent, obs):
        super().__init__(parent)

        self.obs = obs
        self.history = HistoryDB()

        self.event_queue = queue.Queue()
        self._destroying = False
        self._event_poll_id = None
        self._countdown_id = None
        self._periodic_refresh_id = None
        self._screenshot_refresh_id = None

        self.analysis_interval = self._load_interval()
        self.remaining_seconds = self.analysis_interval

        self._last_history_id: Optional[int] = None
        self._last_screenshot_mtime: Optional[float] = None
        self._screenshot_image = None

        self.auto_analyzer = AutoAnalyzer(
            obs=self.obs,
            callback=self.on_auto_analyzer_event,
            interval=self.analysis_interval,
        )

        self._build_ui()
        self.refresh_dashboard(force=True)
        self._start_event_polling()
        self._start_periodic_refresh()
        self._start_screenshot_refresh()

    # ==================================================
    # UI
    # ==================================================



    def _build_ui(self):
        self.configure(
            fg_color=("#F5F7FB", "#0B1120")
        )

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_controls()
        self._build_content()


    def _build_header(self):
        header = ctk.CTkFrame(
            self,
            fg_color="transparent",
        )
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=28,
            pady=(22, 14),
        )
        header.grid_columnconfigure(0, weight=1)

        title_area = ctk.CTkFrame(
            header,
            fg_color="transparent",
        )
        title_area.grid(
            row=0,
            column=0,
            sticky="w",
        )

        ctk.CTkLabel(
            title_area,
            text="\u30e9\u30a4\u30d6\u3092\u3001\u3082\u3063\u3068\u6570\u5b57\u3067\u5f37\u304f\u3002",
            font=("Yu Gothic UI", 31, "bold"),
            text_color="#132347",
        ).pack(
            anchor="w",
        )

        ctk.CTkLabel(
            title_area,
            text="AI\u3067\u914d\u4fe1\u3092\u5206\u6790\u3057\u3001\u3042\u306a\u305f\u306e\u6210\u9577\u3092\u30b5\u30dd\u30fc\u30c8\u3057\u307e\u3059\u3002",
            font=("Yu Gothic UI", 13),
            text_color="#71809C",
        ).pack(
            anchor="w",
            pady=(4, 0),
        )

        status_chip = ctk.CTkFrame(
            header,
            height=38,
            corner_radius=19,
            fg_color="#EEF4FF",
        )
        status_chip.grid(
            row=0,
            column=1,
            sticky="e",
        )

        self.obs_status = ctk.CTkLabel(
            status_chip,
            text="OBS  \u78ba\u8a8d\u4e2d",
            font=("Yu Gothic UI", 11, "bold"),
            text_color="#367BF5",
        )
        self.obs_status.pack(
            padx=16,
            pady=9,
        )


    def _build_controls(self):
        controls = ctk.CTkFrame(
            self,
            corner_radius=18,
            fg_color=("#FFFFFF", "#141C2B"),
            border_width=1,
            border_color=("#E5E7EB", "#263244"),
        )
        controls.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=28,
            pady=(0, 14),
        )

        controls.grid_columnconfigure(1, weight=1)
        controls.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            controls,
            text="\u914d\u4fe1\u30bf\u30a4\u30c8\u30eb",
            font=("Yu Gothic UI", 12, "bold"),
            text_color=("#475569", "#CBD5E1"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(18, 8),
            pady=(15, 5),
        )

        self.title_entry = ctk.CTkEntry(
            controls,
            placeholder_text="\u4f8b\uff1a\u591c\u306eLIVE\u914d\u4fe1",
            height=36,
            corner_radius=10,
        )
        self.title_entry.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 18),
            pady=(15, 5),
        )

        ctk.CTkLabel(
            controls,
            text="TikTok",
            font=("Yu Gothic UI", 12, "bold"),
            text_color=("#475569", "#CBD5E1"),
        ).grid(
            row=0,
            column=2,
            sticky="w",
            padx=(0, 8),
            pady=(15, 5),
        )

        self.username_entry = ctk.CTkEntry(
            controls,
            placeholder_text="@username",
            height=36,
            corner_radius=10,
        )
        self.username_entry.grid(
            row=0,
            column=3,
            sticky="ew",
            padx=(0, 18),
            pady=(15, 5),
        )

        button_row = ctk.CTkFrame(
            controls,
            fg_color="transparent",
        )
        button_row.grid(
            row=1,
            column=0,
            columnspan=4,
            sticky="ew",
            padx=18,
            pady=(8, 8),
        )

        self.start_button = ctk.CTkButton(
            button_row,
            text="\u25b6  LIVE ANALYSIS",
            width=170,
            height=38,
            corner_radius=10,
            fg_color=("#2563EB", "#3B82F6"),
            hover_color=("#1D4ED8", "#2563EB"),
            font=("Yu Gothic UI", 12, "bold"),
            command=self.start_stream,
        )
        self.start_button.pack(
            side="left",
            padx=(0, 8),
        )

        self.stop_button = ctk.CTkButton(
            button_row,
            text="\u25a0  STOP",
            width=100,
            height=38,
            corner_radius=10,
            state="disabled",
            fg_color=("#DC2626", "#EF4444"),
            hover_color=("#B91C1C", "#DC2626"),
            font=("Yu Gothic UI", 12, "bold"),
            command=self.stop_stream,
        )
        self.stop_button.pack(
            side="left",
            padx=4,
        )

        ctk.CTkButton(
            button_row,
            text="\u66f4\u65b0",
            width=90,
            height=38,
            corner_radius=10,
            fg_color="transparent",
            border_width=1,
            border_color=("#CBD5E1", "#475569"),
            text_color=("#334155", "#E2E8F0"),
            hover_color=("#F1F5F9", "#1E293B"),
            command=lambda: self.refresh_dashboard(
                force=True
            ),
        ).pack(
            side="left",
            padx=4,
        )

        self.highlight_button = ctk.CTkButton(
            button_row,
            text="\u30cf\u30a4\u30e9\u30a4\u30c8\u4fdd\u5b58",
            width=140,
            height=38,
            corner_radius=10,
            fg_color="transparent",
            border_width=1,
            border_color=("#CBD5E1", "#475569"),
            text_color=("#334155", "#E2E8F0"),
            hover_color=("#F1F5F9", "#1E293B"),
            command=self.save_highlight_replay,
        )
        self.highlight_button.pack(
            side="left",
            padx=4,
        )

        # Analysis status
        status_row = ctk.CTkFrame(
            controls,
            fg_color="transparent",
        )
        status_row.grid(
            row=2,
            column=0,
            columnspan=4,
            sticky="ew",
            padx=18,
            pady=(4, 6),
        )
        status_row.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(
            status_row,
            text="\u5f85\u6a5f\u4e2d",
            font=("Yu Gothic UI", 12, "bold"),
            text_color=("#0F172A", "#F8FAFC"),
        )
        self.status.grid(
            row=0,
            column=0,
            sticky="w",
        )

        self.countdown_label = ctk.CTkLabel(
            status_row,
            text="\u6b21\u306e\u5206\u6790\u307e\u3067 -- \u79d2",
            font=("Yu Gothic UI", 11),
            text_color=("#64748B", "#94A3B8"),
        )
        self.countdown_label.grid(
            row=0,
            column=1,
            sticky="e",
        )

        self.score_progress = ctk.CTkProgressBar(
            controls,
            height=5,
            corner_radius=3,
            progress_color=("#2563EB", "#60A5FA"),
            fg_color=("#E2E8F0", "#293548"),
        )
        self.score_progress.grid(
            row=3,
            column=0,
            columnspan=4,
            sticky="ew",
            padx=18,
            pady=(0, 5),
        )
        self.score_progress.set(0)

        self.score_gauge_label = ctk.CTkLabel(
            controls,
            text="\u6700\u65b0\u30b9\u30b3\u30a2  -- / 100",
            font=("Yu Gothic UI", 10, "bold"),
            text_color=("#64748B", "#94A3B8"),
        )
        self.score_gauge_label.grid(
            row=4,
            column=0,
            columnspan=4,
            sticky="e",
            padx=18,
            pady=(0, 12),
        )


    def _build_content(self):
        content = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
        )
        content.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=28,
            pady=(0, 24),
        )
        content.grid_columnconfigure(0, weight=1)

        self._build_stats(content)
        self._build_main_panel(content)

    def _build_status_panel(self, parent):
        panel = ctk.CTkFrame(
            parent,
            corner_radius=16,
            fg_color=("#FFFFFF", "#141C2B"),
            border_width=1,
            border_color=("#E5E7EB", "#263244"),
        )
        panel.grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 12),
        )

        panel.grid_columnconfigure(0, weight=1)

        text_area = ctk.CTkFrame(
            panel,
            fg_color="transparent",
        )
        text_area.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=18,
            pady=(13, 8),
        )
        text_area.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(
            text_area,
            text="\u5f85\u6a5f\u4e2d",
            font=("Yu Gothic UI", 14, "bold"),
            text_color=("#0F172A", "#F8FAFC"),
        )
        self.status.grid(
            row=0,
            column=0,
            sticky="w",
        )

        self.countdown_label = ctk.CTkLabel(
            text_area,
            text="\u6b21\u306e\u5206\u6790\u307e\u3067 -- \u79d2",
            font=("Yu Gothic UI", 12),
            text_color=("#64748B", "#94A3B8"),
        )
        self.countdown_label.grid(
            row=0,
            column=1,
            sticky="e",
        )

        self.score_progress = ctk.CTkProgressBar(
            panel,
            height=7,
            corner_radius=4,
            progress_color=("#2563EB", "#60A5FA"),
            fg_color=("#E2E8F0", "#293548"),
        )
        self.score_progress.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=18,
            pady=(0, 8),
        )
        self.score_progress.set(0)

        self.score_gauge_label = ctk.CTkLabel(
            panel,
            text="\u6700\u65b0\u30b9\u30b3\u30a2  -- / 100",
            font=("Yu Gothic UI", 11, "bold"),
            text_color=("#64748B", "#94A3B8"),
        )
        self.score_gauge_label.grid(
            row=2,
            column=0,
            sticky="e",
            padx=18,
            pady=(0, 11),
        )


    def _build_stats(self, parent):
        stats = ctk.CTkFrame(
            parent,
            fg_color="transparent",
        )
        stats.grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 14),
        )

        for column in range(5):
            stats.grid_columnconfigure(
                column,
                weight=1,
                uniform="stats",
            )

        self.count_value = self._create_stat_card(
            stats,
            0,
            "\u7dcf\u5206\u6790\u56de\u6570",
            "0",
            "#2F80ED",
            "#EAF3FF",
            "\u25b6",
        )

        self.average_value = self._create_stat_card(
            stats,
            1,
            "\u5e73\u5747\u30b9\u30b3\u30a2",
            "0",
            "#7C5CFC",
            "#F0ECFF",
            "\u25a5",
        )

        self.max_value = self._create_stat_card(
            stats,
            2,
            "\u6700\u9ad8\u30b9\u30b3\u30a2",
            "0",
            "#F04483",
            "#FFF0F6",
            "\u2605",
        )

        self.min_value = self._create_stat_card(
            stats,
            3,
            "\u6700\u4f4e\u30b9\u30b3\u30a2",
            "0",
            "#66758F",
            "#F0F3F7",
            "!",
        )

        self.today_value = self._create_stat_card(
            stats,
            4,
            "\u4eca\u65e5\u306e\u5206\u6790",
            "0",
            "#18B981",
            "#EAFBF5",
            "\u25a3",
        )


    def _create_stat_card(
        self,
        parent,
        column,
        title,
        value,
        accent,
        soft_color,
        icon,
    ):
        card = ctk.CTkFrame(
            parent,
            height=104,
            corner_radius=18,
            fg_color="#FFFFFF",
            border_width=1,
            border_color="#E7ECF4",
        )
        card.grid(
            row=0,
            column=column,
            sticky="nsew",
            padx=(
                0 if column == 0 else 5,
                0 if column == 4 else 5,
            ),
        )
        card.grid_propagate(False)

        top = ctk.CTkFrame(
            card,
            fg_color="transparent",
        )
        top.pack(
            fill="x",
            padx=14,
            pady=(13, 2),
        )

        icon_box = ctk.CTkFrame(
            top,
            width=34,
            height=34,
            corner_radius=10,
            fg_color=soft_color,
        )
        icon_box.pack(
            side="left",
            padx=(0, 9),
        )
        icon_box.pack_propagate(False)

        ctk.CTkLabel(
            icon_box,
            text=icon,
            font=("Yu Gothic UI", 15, "bold"),
            text_color=accent,
        ).place(
            relx=0.5,
            rely=0.5,
            anchor="center",
        )

        ctk.CTkLabel(
            top,
            text=title,
            font=("Yu Gothic UI", 10, "bold"),
            text_color="#71809C",
        ).pack(
            side="left",
        )

        value_label = ctk.CTkLabel(
            card,
            text=value,
            font=("Yu Gothic UI", 25, "bold"),
            text_color="#132347",
        )
        value_label.pack(
            anchor="w",
            padx=14,
            pady=(0, 10),
        )

        return value_label


    def _build_main_panel(self, parent):
        main = ctk.CTkFrame(
            parent,
            fg_color="transparent",
        )
        main.grid(
            row=1,
            column=0,
            sticky="nsew",
        )

        main.grid_columnconfigure(
            0,
            weight=3,
            uniform="hero",
        )
        main.grid_columnconfigure(
            1,
            weight=2,
            uniform="hero",
        )
        main.grid_rowconfigure(
            0,
            weight=1,
        )

        self._build_screenshot_panel(main)
        self._build_latest_panel(main)
        self._build_graph_panel(main)


    def _build_graph_panel(self, parent):
        frame = ctk.CTkFrame(
            parent,
            corner_radius=18,
            fg_color=("#FFFFFF", "#141C2B"),
            border_width=1,
            border_color=("#E5E7EB", "#263244"),
        )
        frame.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(0, 4),
        )

        header = ctk.CTkFrame(
            frame,
            fg_color="transparent",
        )
        header.pack(
            fill="x",
            padx=18,
            pady=(16, 8),
        )

        ctk.CTkLabel(
            header,
            text="SCORE TREND",
            font=("Yu Gothic UI", 13, "bold"),
            text_color=("#0F172A", "#F8FAFC"),
        ).pack(
            side="left"
        )

        ctk.CTkLabel(
            header,
            text="\u76f4\u8fd1\u306e\u5206\u6790\u30b9\u30b3\u30a2",
            font=("Yu Gothic UI", 10),
            text_color=("#64748B", "#94A3B8"),
        ).pack(
            side="right"
        )

        canvas_bg = (
            "#F8FAFC"
            if ctk.get_appearance_mode() == "Light"
            else "#0F172A"
        )

        self.graph_canvas = ctk.CTkCanvas(
            frame,
            height=230,
            highlightthickness=0,
            bg=canvas_bg,
        )
        self.graph_canvas.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=(0, 16),
        )

        self.graph_canvas.bind(
            "<Configure>",
            lambda _event: self._draw_score_graph(),
        )


    def _build_screenshot_panel(self, parent):
        frame = ctk.CTkFrame(
            parent,
            corner_radius=18,
            fg_color=("#FFFFFF", "#141C2B"),
            border_width=1,
            border_color=("#E5E7EB", "#263244"),
        )
        frame.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 6),
            pady=(0, 12),
        )

        header = ctk.CTkFrame(
            frame,
            fg_color="transparent",
        )
        header.pack(
            fill="x",
            padx=18,
            pady=(16, 10),
        )

        ctk.CTkLabel(
            header,
            text="LIVE PREVIEW",
            font=("Yu Gothic UI", 13, "bold"),
            text_color=("#0F172A", "#F8FAFC"),
        ).pack(
            side="left"
        )

        ctk.CTkLabel(
            header,
            text="OBS",
            font=("Yu Gothic UI", 10, "bold"),
            text_color=("#2563EB", "#60A5FA"),
        ).pack(
            side="right"
        )

        preview = ctk.CTkFrame(
            frame,
            corner_radius=14,
            fg_color=("#F1F5F9", "#0B1120"),
        )
        preview.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=(0, 16),
        )

        self.screenshot_label = ctk.CTkLabel(
            preview,
            text="\u30d7\u30ec\u30d3\u30e5\u30fc\u5f85\u6a5f\u4e2d",
            height=340,
            font=("Yu Gothic UI", 13),
            text_color=("#64748B", "#94A3B8"),
        )
        self.screenshot_label.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=8,
        )




    def _build_latest_panel(self, parent):
        frame = ctk.CTkFrame(
            parent,
            corner_radius=18,
            fg_color=("#FFFFFF", "#141C2B"),
            border_width=1,
            border_color=("#E5E7EB", "#263244"),
        )
        frame.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(6, 0),
            pady=(0, 12),
        )

        header = ctk.CTkFrame(
            frame,
            fg_color="transparent",
        )
        header.pack(
            fill="x",
            padx=18,
            pady=(16, 4),
        )

        ctk.CTkLabel(
            header,
            text="AI LIVE INSIGHT",
            font=("Yu Gothic UI", 13, "bold"),
            text_color=("#2563EB", "#60A5FA"),
        ).pack(side="left")

        self.latest_date = ctk.CTkLabel(
            header,
            text="--",
            font=("Yu Gothic UI", 10),
            text_color=("#64748B", "#94A3B8"),
        )
        self.latest_date.pack(side="right")

        score_area = ctk.CTkFrame(
            frame,
            fg_color="transparent",
        )
        score_area.pack(
            fill="x",
            padx=18,
            pady=(6, 8),
        )

        ctk.CTkLabel(
            score_area,
            text="LIVE SCORE",
            font=("Yu Gothic UI", 10, "bold"),
            text_color=("#64748B", "#94A3B8"),
        ).pack(anchor="w")

        number_row = ctk.CTkFrame(
            score_area,
            fg_color="transparent",
        )
        number_row.pack(anchor="w")

        self.latest_score = ctk.CTkLabel(
            number_row,
            text="--",
            font=("Yu Gothic UI", 46, "bold"),
            text_color=("#0F172A", "#F8FAFC"),
        )
        self.latest_score.pack(side="left")

        ctk.CTkLabel(
            number_row,
            text="/ 100",
            font=("Yu Gothic UI", 17, "bold"),
            text_color=("#94A3B8", "#64748B"),
        ).pack(
            side="left",
            padx=(8, 0),
            pady=(18, 0),
        )

        insight_container = ctk.CTkFrame(
            frame,
            fg_color="transparent",
        )
        insight_container.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=(0, 16),
        )

        def make_insight_card(
            title,
            accent_light,
            accent_dark,
        ):
            card = ctk.CTkFrame(
                insight_container,
                corner_radius=12,
                fg_color=("#F8FAFC", "#0F172A"),
                border_width=1,
                border_color=("#E5E7EB", "#263244"),
            )
            card.pack(
                fill="x",
                pady=3,
            )

            ctk.CTkLabel(
                card,
                text=title,
                font=("Yu Gothic UI", 11, "bold"),
                text_color=(accent_light, accent_dark),
            ).pack(
                anchor="w",
                padx=14,
                pady=(8, 3),
            )

            body = ctk.CTkLabel(
                card,
                text="--",
                justify="left",
                anchor="w",
                wraplength=390,
                font=("Yu Gothic UI", 11),
                text_color=("#334155", "#E2E8F0"),
            )
            body.pack(
                fill="x",
                padx=14,
                pady=(0, 8),
            )

            return body

        self.insight_observation = make_insight_card(
            "\u2726  AI\u306e\u898b\u7acb\u3066",
            "#2563EB",
            "#60A5FA",
        )

        self.insight_problem = make_insight_card(
            "\u25b3  \u6539\u5584\u30dd\u30a4\u30f3\u30c8",
            "#D97706",
            "#FBBF24",
        )

        self.insight_action = make_insight_card(
            "\u2713  \u6b21\u306b\u3084\u308b\u3053\u3068",
            "#059669",
            "#34D399",
        )

    def start_stream(self):
        try:
            if not self.obs.is_connected():
                self._set_obs_status(False)
                self.status.configure(
                    text="❌ OBSに接続されていません"
                )
                return

            if self.auto_analyzer.is_running():
                self.status.configure(
                    text="⚠️ AI分析はすでに実行中です"
                )
                return

            self.analysis_interval = self._load_interval()
            self.remaining_seconds = self.analysis_interval

            # AutoAnalyzerが実行前なら設定画面の最新値を反映
            if hasattr(self.auto_analyzer, "interval"):
                self.auto_analyzer.interval = self.analysis_interval

            self._set_obs_status(True)
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            self.status.configure(
                text="🟢 AI分析を開始しました"
            )
            self.countdown_label.configure(
                text="最初の分析を実行中..."
            )

            self.auto_analyzer.start()

        except Exception as exc:
            self.status.configure(
                text=(
                    "❌ 開始エラー："
                    f"{type(exc).__name__}: {exc}"
                )
            )
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")

    def stop_stream(self):
        try:
            self.auto_analyzer.stop()
            self._cancel_countdown()

            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")

            self.status.configure(
                text="⏹ AI分析を停止しました"
            )

            self.countdown_label.configure(
                text="次の分析まで：--秒"
            )

        except Exception as exc:
            self.status.configure(
                text=(
                    "❌ 停止エラー："
                    f"{type(exc).__name__}: {exc}"
                )
            )

    def save_highlight_replay(self):
        try:
            if not self.obs.is_connected():
                self.status.configure(
                    text="❌ OBSに接続されていません"
                )
                return

            if not self.obs.is_replay_buffer_active():
                self.status.configure(
                    text="⚠️ リプレイバッファが開始されていません"
                )
                return

            success = self.obs.save_replay_buffer()

            if success:
                self.status.configure(
                    text="🔥 盛り上がり映像を保存しました"
                )
            else:
                self.status.configure(
                    text="❌ 盛り上がり映像の保存に失敗しました"
                )

        except Exception as exc:
            self.status.configure(
                text=(
                    "❌ リプレイ保存エラー："
                    f"{type(exc).__name__}: {exc}"
                )
            )

# ==================================================
# Background events
# ==================================================    

    def on_auto_analyzer_event(self, event, data):
        if self._destroying:
            return

        self.event_queue.put((event, data))

    def _start_event_polling(self):
        if self._destroying:
            return

        self._process_event_queue()
        self._event_poll_id = self.after(
            100,
            self._start_event_polling,
        )

    def _process_event_queue(self):
        while True:
            try:
                event, data = self.event_queue.get_nowait()
            except queue.Empty:
                break

            self._handle_auto_analyzer_event(event, data)

    def _handle_auto_analyzer_event(self, event, data):
        if self._destroying:
            return

        try:
            if event == "status":
                self.status.configure(
                    text=f"🤖 {data}"
                )
                self._cancel_countdown()
                self.countdown_label.configure(
                    text="現在の分析を実行中..."
                )

            elif event == "error":
                self.status.configure(
                    text=f"❌ {data}"
                )

                if self.auto_analyzer.is_running():
                    self._restart_countdown()

            elif event == "result":
                score = data.get("score") if isinstance(data, dict) else None
                score_text = "--" if score is None else str(score)

                self.status.configure(
                    text=f"✅ 分析完了（{score_text}点）"
                )
                self.refresh_dashboard(force=True)
                self.refresh_screenshot(force=True)

                if self.auto_analyzer.is_running():
                    self._restart_countdown()

        except Exception as exc:
            print(
                "Dashboardイベント処理エラー:",
                repr(exc),
            )

    # ==================================================
    # Countdown
    # ==================================================

    def _restart_countdown(self):
        self._cancel_countdown()
        self.remaining_seconds = self.analysis_interval
        self._update_countdown()

    def _update_countdown(self):
        if self._destroying:
            return

        if not self.auto_analyzer.is_running():
            self.countdown_label.configure(
                text="次の分析まで：--秒"
            )
            return

        if self.remaining_seconds <= 0:
            self.countdown_label.configure(
                text="次の分析を開始します..."
            )
            return

        self.countdown_label.configure(
            text=f"次の分析まで：{self.remaining_seconds}秒"
        )

        self.remaining_seconds -= 1
        self._countdown_id = self.after(
            1000,
            self._update_countdown,
        )

    def _cancel_countdown(self):
        if self._countdown_id is None:
            return

        try:
            self.after_cancel(self._countdown_id)
        except Exception:
            pass

        self._countdown_id = None

    # ==================================================
    # Dashboard refresh
    # ==================================================

    def refresh_dashboard(self, force=False):
        if self._destroying:
            return

        try:
            self._set_obs_status(
                self.obs.is_connected()
            )

            count = self.history.get_count()
            average = self.history.get_average()
            maximum = self.history.get_max()
            minimum = self.history.get_min()
            today = self.history.get_today_count()
            latest = self.history.get_latest()

            self.count_value.configure(
                text=f"{self._display_number(count)}回"
            )
            self.average_value.configure(
                text=f"{self._display_number(average)}点"
            )
            self.max_value.configure(
                text=f"{self._display_number(maximum)}点"
            )
            self.min_value.configure(
                text=f"{self._display_number(minimum)}点"
            )
            self.today_value.configure(
                text=f"{self._display_number(today)}回"
            )

            latest_id = latest[0] if latest else None
            if force or latest_id != self._last_history_id:
                self._last_history_id = latest_id
                self._update_latest_result(latest)
                self._draw_score_graph()

        except Exception as exc:
            print(
                "Dashboard更新エラー:",
                repr(exc),
            )



    @staticmethod
    def _compact_insight_text(value, max_chars=110):
        value = str(value or "").strip()

        value = " ".join(
            line.strip()
            for line in value.splitlines()
            if line.strip()
        )

        if value.startswith("1."):
            value = value[2:].strip()

        if len(value) <= max_chars:
            return value

        return value[:max_chars].rstrip() + "?"

    @staticmethod
    def _parse_analysis_sections(result):
        text = str(result or "").strip()

        if not text:
            return {
                "observation": "\u5206\u6790\u7d50\u679c\u306f\u3042\u308a\u307e\u305b\u3093\u3002",
                "problem": "--",
                "action": "--",
            }

        sections = {}
        current = None
        buffer = []

        def flush():
            nonlocal buffer

            if current is not None:
                value = "\n".join(buffer).strip()
                if value:
                    sections[current] = value

            buffer = []

        for line in text.splitlines():
            stripped = line.strip()

            if (
                stripped.startswith("\u3010")
                and stripped.endswith("\u3011")
            ):
                flush()
                current = stripped[1:-1]
                continue

            buffer.append(line)

        flush()

        observation = (
            sections.get("\u826f\u3044\u70b9")
            or sections.get("\u72b6\u614b")
            or sections.get("AI\u306b\u3088\u308b\u753b\u9762\u5206\u6790")
            or text
        )

        problem = (
            sections.get("\u6539\u5584\u70b9")
            or sections.get("\u5206\u6790\u7406\u7531")
            or "--"
        )

        action = (
            sections.get("\u3059\u3050\u5b9f\u884c\u3067\u304d\u308b\u6539\u5584\u6848")
            or sections.get("\u6700\u512a\u5148\u306e\u6539\u5584")
            or "--"
        )

        return {
            "observation": observation.strip(),
            "problem": problem.strip(),
            "action": action.strip(),
        }

    def _update_latest_result(self, latest):
        if latest:
            created_at = latest[1]
            score = latest[2]

            result = (
                latest[4]
                if len(latest) > 4
                else ""
            )

            numeric_score = self._safe_score(score)

            self.latest_date.configure(
                text=str(created_at)
            )

            self.latest_score.configure(
                text=(
                    "--"
                    if numeric_score is None
                    else f"{numeric_score:g}"
                )
            )

            sections = self._parse_analysis_sections(
                result
            )

            self.insight_observation.configure(
                text=self._compact_insight_text(
                    sections["observation"]
                )
            )

            self.insight_problem.configure(
                text=self._compact_insight_text(
                    sections["problem"]
                )
            )

            self.insight_action.configure(
                text=self._compact_insight_text(
                    sections["action"]
                )
            )

            if numeric_score is None:
                self.score_progress.set(0)
                self.score_gauge_label.configure(
                    text="\u6700\u65b0\u30b9\u30b3\u30a2  -- / 100"
                )
            else:
                self.score_progress.set(
                    numeric_score / 100
                )

                self.score_gauge_label.configure(
                    text=(
                        "\u6700\u65b0\u30b9\u30b3\u30a2  "
                        f"{numeric_score:g} / 100"
                    )
                )

        else:
            self.latest_date.configure(
                text="--"
            )

            self.latest_score.configure(
                text="--"
            )

            self.insight_observation.configure(
                text="\u307e\u3060\u5206\u6790\u5c65\u6b74\u306f\u3042\u308a\u307e\u305b\u3093\u3002"
            )

            self.insight_problem.configure(
                text="--"
            )

            self.insight_action.configure(
                text="--"
            )

            self.score_progress.set(0)

            self.score_gauge_label.configure(
                text="\u6700\u65b0\u30b9\u30b3\u30a2  -- / 100"
            )

    def _draw_score_graph(self):
        if self._destroying:
            return

        canvas = self.graph_canvas

        is_light = (
            ctk.get_appearance_mode() == "Light"
        )

        background = (
            "#F8FAFC"
            if is_light
            else "#0F172A"
        )

        grid_color = (
            "#E2E8F0"
            if is_light
            else "#263244"
        )

        axis_text_color = (
            "#64748B"
            if is_light
            else "#94A3B8"
        )

        empty_text_color = (
            "#94A3B8"
            if is_light
            else "#64748B"
        )

        line_color = (
            "#2563EB"
            if is_light
            else "#60A5FA"
        )

        point_fill = (
            "#FFFFFF"
            if is_light
            else "#0F172A"
        )

        canvas.configure(
            bg=background
        )

        canvas.delete("all")

        width = max(
            canvas.winfo_width(),
            420,
        )
        height = max(
            canvas.winfo_height(),
            240,
        )

        margin_left = 40
        margin_right = 18
        margin_top = 16
        margin_bottom = 30

        plot_width = (
            width
            - margin_left
            - margin_right
        )

        plot_height = (
            height
            - margin_top
            - margin_bottom
        )

        try:
            rows = self.history.get_all()[
                :self.GRAPH_LIMIT
            ]
        except Exception:
            rows = []

        points = []

        for row in reversed(rows):
            if len(row) <= 2:
                continue

            score = self._safe_score(
                row[2]
            )

            if score is not None:
                points.append(score)

        for value in (
            0,
            25,
            50,
            75,
            100,
        ):
            y = (
                margin_top
                + plot_height
                * (1 - value / 100)
            )

            canvas.create_line(
                margin_left,
                y,
                width - margin_right,
                y,
                fill=grid_color,
                width=1,
            )

            canvas.create_text(
                margin_left - 8,
                y,
                text=str(value),
                fill=axis_text_color,
                anchor="e",
                font=(
                    "Yu Gothic UI",
                    9,
                ),
            )

        if not points:
            canvas.create_text(
                width / 2,
                height / 2,
                text="\u30b9\u30b3\u30a2\u5c65\u6b74\u306f\u307e\u3060\u3042\u308a\u307e\u305b\u3093",
                fill=empty_text_color,
                font=(
                    "Yu Gothic UI",
                    13,
                ),
            )
            return

        if len(points) == 1:
            x_values = [
                margin_left
                + plot_width / 2
            ]
        else:
            x_values = [
                margin_left
                + plot_width
                * index
                / (len(points) - 1)
                for index
                in range(len(points))
            ]

        coordinates = []

        for x, score in zip(
            x_values,
            points,
        ):
            y = (
                margin_top
                + plot_height
                * (1 - score / 100)
            )

            coordinates.extend(
                [x, y]
            )

        if len(points) >= 2:
            canvas.create_line(
                *coordinates,
                fill=line_color,
                width=3,
                smooth=True,
            )

        for index, (
            x,
            score,
        ) in enumerate(
            zip(
                x_values,
                points,
            ),
            start=1,
        ):
            y = (
                margin_top
                + plot_height
                * (1 - score / 100)
            )

            canvas.create_oval(
                x - 4,
                y - 4,
                x + 4,
                y + 4,
                fill=point_fill,
                outline=line_color,
                width=2,
            )

            if (
                len(points) <= 10
                or index in (
                    1,
                    len(points),
                )
            ):
                canvas.create_text(
                    x,
                    height - 12,
                    text=str(index),
                    fill=axis_text_color,
                    font=(
                        "Yu Gothic UI",
                        9,
                    ),
                )

    # ==================================================
    # Screenshot
    # ==================================================

    def _get_screenshot_path(self):
        base = os.getenv("LOCALAPPDATA")

        if not base:
            base = os.path.join(
                os.path.expanduser("~"),
                "AppData",
                "Local",
            )

        default = (
            Path(base)
            / "AI-TikTok-LIVE-Analyzer"
            / "images"
            / "current.png"
        )

        try:
            settings = Settings.load()

            configured = settings.get(
                "screenshot_path",
                "images/current.png",
            )

            configured_path = Path(configured)

            if configured_path.is_absolute():
                return configured_path

            return (
                Path(base)
                / "AI-TikTok-LIVE-Analyzer"
                / configured_path
            )

        except Exception:
            return default

    def _screenshot_widget_alive(self):
        """スクリーンショット表示先がまだ有効か確認する。"""
        if self._destroying:
            return False
        label = getattr(self, "screenshot_label", None)
        if label is None:
            return False
        try:
            return bool(self.winfo_exists()) and bool(label.winfo_exists())
        except Exception:
            return False

    def _clear_screenshot(self, text="画像がまだありません"):
        """破棄済みWidgetを触らず、安全に画像表示をクリアする。"""
        if not self._screenshot_widget_alive():
            return
        self._screenshot_image = None
        try:
            self.screenshot_label.configure(image=None, text=text)
        except Exception:
            pass

    def refresh_screenshot(self, force=False):
        if not self._screenshot_widget_alive():
            return

        path = self._get_screenshot_path()

        if not path.exists():
            if force:
                self._last_screenshot_mtime = None
                self._clear_screenshot("画像がまだありません")
            return

        try:
            modified = path.stat().st_mtime

            if (
                not force
                and self._last_screenshot_mtime == modified
                and self._screenshot_image is not None
            ):
                return

            with Image.open(path) as source_image:
                image = source_image.convert("RGB")
                image.thumbnail((520, 290))
                display_image = image.copy()

            new_image = ctk.CTkImage(
                light_image=display_image,
                dark_image=display_image,
                size=display_image.size,
            )

            # configure前に参照を保持してGCを防ぐ
            self._screenshot_image = new_image

            if not self._screenshot_widget_alive():
                return

            self.screenshot_label.configure(
                image=new_image,
                text="",
            )
            self._last_screenshot_mtime = modified

        except Exception as exc:
            print("スクリーンショット表示エラー:", repr(exc))
            self._last_screenshot_mtime = None
            # エラー処理中のconfigureで二重例外を起こさない
            self._clear_screenshot(
                f"画像を表示できません\\n{type(exc).__name__}: {exc}"
            )

    # ==================================================
    # Periodic refresh
    # ==================================================

    def _start_periodic_refresh(self):
        if self._destroying:
            return

        self.refresh_dashboard()
        self._periodic_refresh_id = self.after(
            self.DASHBOARD_REFRESH_MS,
            self._start_periodic_refresh,
        )

    def _start_screenshot_refresh(self):
        if self._destroying:
            return

        self.refresh_screenshot()
        self._screenshot_refresh_id = self.after(
            self.SCREENSHOT_REFRESH_MS,
            self._start_screenshot_refresh,
        )

    # ==================================================
    # Helpers
    # ==================================================

    def _load_interval(self):
        try:
            settings = Settings.load()

            interval = int(
                settings.get(
                    "analysis_interval",
                    self.DEFAULT_INTERVAL,
                )
            )

            if interval <= 0:
                return self.DEFAULT_INTERVAL

            return interval

        except Exception:
            return self.DEFAULT_INTERVAL

    def _set_obs_status(self, connected):
        if connected:
            self.obs_status.configure(
                text="📡 OBS状態：接続済み"
            )
        else:
            self.obs_status.configure(
                text="📡 OBS状態：未接続"
            )

    @staticmethod
    def _safe_score(value: Any) -> Optional[float]:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return None

        return max(0.0, min(100.0, score))

    @staticmethod
    def _display_number(value):
        return 0 if value is None else value

    @staticmethod
    def _set_textbox(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", str(text))
        widget.configure(state="disabled")

    # ==================================================
    # Cleanup
    # ==================================================

    def destroy(self):
        if self._destroying:
            return

        self._destroying = True

        try:
            self.auto_analyzer.stop()
        except Exception:
            pass

        self._cancel_countdown()

        for job_name in (
            "_event_poll_id",
            "_periodic_refresh_id",
            "_screenshot_refresh_id",
        ):
            job_id = getattr(self, job_name, None)

            if job_id is not None:
                try:
                    self.after_cancel(job_id)
                except Exception:
                    pass

                setattr(self, job_name, None)

        super().destroy()