import json
import queue
from pathlib import Path
from typing import Any, Optional

import customtkinter as ctk
from PIL import Image

from core.auto_analyzer import AutoAnalyzer
from core.history import HistoryDB


class DashboardPage(ctk.CTkFrame):
    """AI TikTok LIVE Analyzer ダッシュボード完成版。"""

    DEFAULT_INTERVAL = 30
    SETTINGS_PATH = Path("settings.json")
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
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_controls()
        self._build_content()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=20,
            pady=(18, 8),
        )
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="📊 AI TikTok LIVE Dashboard",
            font=("Yu Gothic UI", 24, "bold"),
        ).grid(row=0, column=0, sticky="w")

        self.obs_status = ctk.CTkLabel(
            header,
            text="📡 OBS状態：確認中",
            font=("Yu Gothic UI", 14, "bold"),
        )
        self.obs_status.grid(
            row=0,
            column=2,
            sticky="e",
        )

    def _build_controls(self):
        controls = ctk.CTkFrame(self)
        controls.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=20,
            pady=(0, 10),
        )
        controls.grid_columnconfigure(1, weight=1)
        controls.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            controls,
            text="配信タイトル",
            font=("Yu Gothic UI", 13, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(14, 8),
            pady=(12, 4),
        )

        self.title_entry = ctk.CTkEntry(
            controls,
            placeholder_text="例：雑談LIVE",
        )
        self.title_entry.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 16),
            pady=(12, 4),
        )

        ctk.CTkLabel(
            controls,
            text="TikTokユーザー名",
            font=("Yu Gothic UI", 13, "bold"),
        ).grid(
            row=0,
            column=2,
            sticky="w",
            padx=(0, 8),
            pady=(12, 4),
        )

        self.username_entry = ctk.CTkEntry(
            controls,
            placeholder_text="@username",
        )
        self.username_entry.grid(
            row=0,
            column=3,
            sticky="ew",
            padx=(0, 14),
            pady=(12, 4),
        )

        button_row = ctk.CTkFrame(
            controls,
            fg_color="transparent",
        )
        button_row.grid(
            row=1,
            column=0,
            columnspan=4,
            pady=(8, 12),
        )

        self.start_button = ctk.CTkButton(
            button_row,
            text="▶ AI分析開始",
            width=170,
            height=38,
            command=self.start_stream,
        )
        self.start_button.pack(side="left", padx=6)

        self.stop_button = ctk.CTkButton(
            button_row,
            text="■ AI分析停止",
            width=170,
            height=38,
            state="disabled",
            fg_color="#B91C1C",
            hover_color="#991B1B",
            command=self.stop_stream,
        )
        self.stop_button.pack(side="left", padx=6)

        ctk.CTkButton(
            button_row,
            text="🔄 今すぐ更新",
            width=150,
            height=38,
            command=lambda: self.refresh_dashboard(force=True),
        ).pack(side="left", padx=6)

    def _build_content(self):
        content = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
        )
        content.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=20,
            pady=(0, 18),
        )
        content.grid_columnconfigure(0, weight=1)

        self._build_status_panel(content)
        self._build_stats(content)
        self._build_main_panel(content)

    def _build_status_panel(self, parent):
        panel = ctk.CTkFrame(parent)
        panel.grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 10),
        )
        panel.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(
            panel,
            text="ステータス：待機中",
            font=("Yu Gothic UI", 15, "bold"),
        )
        self.status.grid(
            row=0,
            column=0,
            pady=(12, 4),
        )

        self.countdown_label = ctk.CTkLabel(
            panel,
            text="次の分析まで：--秒",
            font=("Yu Gothic UI", 13),
        )
        self.countdown_label.grid(
            row=1,
            column=0,
            pady=(0, 6),
        )

        self.score_progress = ctk.CTkProgressBar(
            panel,
            height=14,
        )
        self.score_progress.grid(
            row=2,
            column=0,
            sticky="ew",
            padx=50,
            pady=(4, 4),
        )
        self.score_progress.set(0)

        self.score_gauge_label = ctk.CTkLabel(
            panel,
            text="最新スコア：-- / 100",
            font=("Yu Gothic UI", 13, "bold"),
        )
        self.score_gauge_label.grid(
            row=3,
            column=0,
            pady=(0, 12),
        )

    def _build_stats(self, parent):
        stats = ctk.CTkFrame(
            parent,
            fg_color="transparent",
        )
        stats.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(0, 10),
        )

        for column in range(5):
            stats.grid_columnconfigure(column, weight=1)

        self.count_value = self._create_stat_card(
            stats, 0, "📊 総分析", "0回"
        )
        self.average_value = self._create_stat_card(
            stats, 1, "⭐ 平均", "0点"
        )
        self.max_value = self._create_stat_card(
            stats, 2, "🏆 最高", "0点"
        )
        self.min_value = self._create_stat_card(
            stats, 3, "📉 最低", "0点"
        )
        self.today_value = self._create_stat_card(
            stats, 4, "📅 今日", "0回"
        )

    def _create_stat_card(self, parent, column, title, value):
        card = ctk.CTkFrame(
            parent,
            corner_radius=12,
        )
        card.grid(
            row=0,
            column=column,
            sticky="nsew",
            padx=4,
        )

        ctk.CTkLabel(
            card,
            text=title,
            font=("Yu Gothic UI", 13, "bold"),
        ).pack(pady=(12, 2))

        value_label = ctk.CTkLabel(
            card,
            text=value,
            font=("Yu Gothic UI", 25, "bold"),
        )
        value_label.pack(pady=(0, 12))

        return value_label

    def _build_main_panel(self, parent):
        main = ctk.CTkFrame(
            parent,
            fg_color="transparent",
        )
        main.grid(
            row=2,
            column=0,
            sticky="nsew",
        )
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)

        self._build_graph_panel(main)
        self._build_screenshot_panel(main)
        self._build_latest_panel(main)

    def _build_graph_panel(self, parent):
        frame = ctk.CTkFrame(parent)
        frame.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 5),
            pady=(0, 10),
        )

        ctk.CTkLabel(
            frame,
            text="📈 直近スコア推移",
            font=("Yu Gothic UI", 17, "bold"),
        ).pack(
            anchor="w",
            padx=14,
            pady=(12, 6),
        )

        self.graph_canvas = ctk.CTkCanvas(
            frame,
            height=260,
            highlightthickness=0,
            bg="#242424",
        )
        self.graph_canvas.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(0, 14),
        )
        self.graph_canvas.bind(
            "<Configure>",
            lambda _event: self._draw_score_graph(),
        )

    def _build_screenshot_panel(self, parent):
        frame = ctk.CTkFrame(parent)
        frame.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(5, 0),
            pady=(0, 10),
        )

        ctk.CTkLabel(
            frame,
            text="🖼 最新スクリーンショット",
            font=("Yu Gothic UI", 17, "bold"),
        ).pack(
            anchor="w",
            padx=14,
            pady=(12, 6),
        )

        self.screenshot_label = ctk.CTkLabel(
            frame,
            text="画像がまだありません",
            height=260,
        )
        self.screenshot_label.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(0, 14),
        )

    def _build_latest_panel(self, parent):
        frame = ctk.CTkFrame(parent)
        frame.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="nsew",
        )

        header = ctk.CTkFrame(
            frame,
            fg_color="transparent",
        )
        header.pack(
            fill="x",
            padx=14,
            pady=(12, 6),
        )

        ctk.CTkLabel(
            header,
            text="📋 最新のAI分析結果",
            font=("Yu Gothic UI", 17, "bold"),
        ).pack(side="left")

        self.latest_date = ctk.CTkLabel(
            header,
            text="日時：--",
        )
        self.latest_date.pack(
            side="right",
        )

        self.latest_score = ctk.CTkLabel(
            frame,
            text="スコア：--",
            font=("Yu Gothic UI", 15, "bold"),
        )
        self.latest_score.pack(
            anchor="w",
            padx=14,
            pady=(0, 4),
        )

        self.latest_text = ctk.CTkTextbox(
            frame,
            height=220,
            wrap="word",
        )
        self.latest_text.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(0, 14),
        )
        self._set_textbox(
            self.latest_text,
            "まだ分析履歴がありません。",
        )

    # ==================================================
    # Start / stop
    # ==================================================

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

    def _update_latest_result(self, latest):
        if latest:
            created_at = latest[1]
            score = latest[2]
            result = (
                latest[4]
                if len(latest) > 4
                else "分析結果を取得できませんでした。"
            )

            score_text = "--" if score is None else str(score)

            self.latest_date.configure(
                text=f"日時：{created_at}"
            )
            self.latest_score.configure(
                text=f"スコア：{score_text} 点"
            )
            self._set_textbox(
                self.latest_text,
                result or "分析結果が空です。",
            )

            numeric_score = self._safe_score(score)
            if numeric_score is None:
                self.score_progress.set(0)
                self.score_gauge_label.configure(
                    text="最新スコア：-- / 100"
                )
            else:
                self.score_progress.set(
                    numeric_score / 100
                )
                self.score_gauge_label.configure(
                    text=f"最新スコア：{numeric_score:g} / 100"
                )

        else:
            self.latest_date.configure(
                text="日時：--"
            )
            self.latest_score.configure(
                text="スコア：--"
            )
            self.score_progress.set(0)
            self.score_gauge_label.configure(
                text="最新スコア：-- / 100"
            )
            self._set_textbox(
                self.latest_text,
                "まだ分析履歴がありません。",
            )

    def _draw_score_graph(self):
        if self._destroying:
            return

        canvas = self.graph_canvas
        canvas.delete("all")

        width = max(canvas.winfo_width(), 420)
        height = max(canvas.winfo_height(), 240)

        margin_left = 40
        margin_right = 18
        margin_top = 16
        margin_bottom = 30

        plot_width = width - margin_left - margin_right
        plot_height = height - margin_top - margin_bottom

        try:
            rows = self.history.get_all()[:self.GRAPH_LIMIT]
        except Exception:
            rows = []

        points = []
        for row in reversed(rows):
            if len(row) <= 2:
                continue

            score = self._safe_score(row[2])
            if score is not None:
                points.append(score)

        # 補助線
        for value in (0, 25, 50, 75, 100):
            y = margin_top + plot_height * (1 - value / 100)

            canvas.create_line(
                margin_left,
                y,
                width - margin_right,
                y,
                fill="#4A4A4A",
                width=1,
            )
            canvas.create_text(
                margin_left - 8,
                y,
                text=str(value),
                fill="#CFCFCF",
                anchor="e",
                font=("Yu Gothic UI", 9),
            )

        if not points:
            canvas.create_text(
                width / 2,
                height / 2,
                text="スコア履歴がありません",
                fill="#BDBDBD",
                font=("Yu Gothic UI", 14),
            )
            return

        if len(points) == 1:
            x_values = [margin_left + plot_width / 2]
        else:
            x_values = [
                margin_left + plot_width * index / (len(points) - 1)
                for index in range(len(points))
            ]

        coordinates = []
        for x, score in zip(x_values, points):
            y = margin_top + plot_height * (1 - score / 100)
            coordinates.extend([x, y])

        if len(points) >= 2:
            canvas.create_line(
                *coordinates,
                fill="#3B8ED0",
                width=3,
                smooth=True,
            )

        for index, (x, score) in enumerate(zip(x_values, points), start=1):
            y = margin_top + plot_height * (1 - score / 100)

            canvas.create_oval(
                x - 4,
                y - 4,
                x + 4,
                y + 4,
                fill="#FFFFFF",
                outline="#3B8ED0",
                width=2,
            )

            if len(points) <= 10 or index in (1, len(points)):
                canvas.create_text(
                    x,
                    height - 12,
                    text=str(index),
                    fill="#BDBDBD",
                    font=("Yu Gothic UI", 9),
                )

    # ==================================================
    # Screenshot
    # ==================================================

    def _get_screenshot_path(self):
        default = Path("images/current.png")

        if not self.SETTINGS_PATH.exists():
            return default

        try:
            with self.SETTINGS_PATH.open(
                "r",
                encoding="utf-8",
            ) as file:
                settings = json.load(file)

            configured = settings.get(
                "screenshot_path",
                str(default),
            )
            return Path(configured)

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
        if not self.SETTINGS_PATH.exists():
            return self.DEFAULT_INTERVAL

        try:
            with self.SETTINGS_PATH.open(
                "r",
                encoding="utf-8",
            ) as file:
                settings = json.load(file)

            interval = int(
                settings.get(
                    "analysis_interval",
                    self.DEFAULT_INTERVAL,
                )
            )

            if 10 <= interval <= 3600:
                return interval

        except Exception:
            pass

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