import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.gift_analyzer import GiftAnalyzer
from core.gift_frame_gate import GiftFrameGate
from core.gift_monitor_controller import GiftMonitorController
from core.gift_monitor_worker import GiftMonitorWorker
from core.gift_obs_monitor import GiftOBSMonitor
from core.gift_stream_analyzer import GiftStreamAnalyzer
from core.history import HistoryDB


def resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent.parent.parent

    return str(base_path / relative_path)


class GiftPage(ctk.CTkFrame):
    """ギフト検出・履歴ページ。"""

    HISTORY_LIMIT = 100

    def __init__(self, master, obs):
        super().__init__(master)

        self.obs = obs
        self.history = HistoryDB()
        self.selected_image_path = None

        catalog_path = resource_path(
            "data/gifts/gift_catalog.json"
        )

        self.analyzer = GiftAnalyzer(
            catalog_path=catalog_path,
            history_db=self.history,
        )

        self.stream_analyzer = GiftStreamAnalyzer(
            catalog_path=catalog_path,
            history_db=self.history,
        )

        self.monitor_controller = GiftMonitorController(
            stream_analyzer=self.stream_analyzer,
            frame_gate=GiftFrameGate(
                analyze_first_frame=False,
            ),
        )

        self.obs_monitor = GiftOBSMonitor(
            obs=self.obs,
            controller=self.monitor_controller,
            screenshot_path="images/gift_monitor.png",
        )

        self.monitor_worker = GiftMonitorWorker(
            monitor=self.obs_monitor,
            capture_interval_seconds=1.0,
            max_capture_backlog=30,
        )

        self.monitoring = False
        self.monitor_busy = False
        self.monitor_after_id = None
        self.monitor_interval_ms = 1000

        self._build_ui()
        self.load_history()

    def _build_ui(self):
        header = ctk.CTkFrame(
            self,
            fg_color="transparent",
        )
        header.pack(
            fill="x",
            padx=24,
            pady=(24, 12),
        )

        title = ctk.CTkLabel(
            header,
            text="🎁 ギフト分析",
            font=ctk.CTkFont(
                size=26,
                weight="bold",
            ),
        )
        title.pack(
            side="left",
        )

        refresh_button = ctk.CTkButton(
            header,
            text="更新",
            width=100,
            command=self.load_history,
        )
        refresh_button.pack(
            side="right",
        )

        analysis_frame = ctk.CTkFrame(
            self,
        )
        analysis_frame.pack(
            fill="x",
            padx=24,
            pady=(0, 16),
        )

        analysis_title = ctk.CTkLabel(
            analysis_frame,
            text="画像からギフトを分析",
            font=ctk.CTkFont(
                size=18,
                weight="bold",
            ),
        )
        analysis_title.pack(
            anchor="w",
            padx=18,
            pady=(16, 8),
        )

        button_frame = ctk.CTkFrame(
            analysis_frame,
            fg_color="transparent",
        )
        button_frame.pack(
            fill="x",
            padx=18,
            pady=(0, 8),
        )

        select_button = ctk.CTkButton(
            button_frame,
            text="画像を選択",
            width=130,
            command=self.select_image,
        )
        select_button.pack(
            side="left",
        )

        self.analyze_button = ctk.CTkButton(
            button_frame,
            text="AI分析を実行",
            width=130,
            command=self.start_analysis,
            state="disabled",
        )
        self.analyze_button.pack(
            side="left",
            padx=(10, 0),
        )

        self.obs_analyze_button = ctk.CTkButton(
            button_frame,
            text="OBSから取得して分析",
            width=170,
            command=self.start_obs_analysis,
        )
        self.obs_analyze_button.pack(
            side="left",
            padx=(10, 0),
        )

        self.selected_image_label = ctk.CTkLabel(
            analysis_frame,
            text="画像が選択されていません。",
            anchor="w",
        )
        self.selected_image_label.pack(
            fill="x",
            padx=18,
            pady=(0, 6),
        )

        self.analysis_status_label = ctk.CTkLabel(
            analysis_frame,
            text="",
            anchor="w",
        )
        self.analysis_status_label.pack(
            fill="x",
            padx=18,
            pady=(0, 16),
        )

        monitor_frame = ctk.CTkFrame(
            self,
        )
        monitor_frame.pack(
            fill="x",
            padx=24,
            pady=(0, 16),
        )

        monitor_title = ctk.CTkLabel(
            monitor_frame,
            text="OBS ギフト監視",
            font=ctk.CTkFont(
                size=18,
                weight="bold",
            ),
        )
        monitor_title.pack(
            anchor="w",
            padx=18,
            pady=(16, 8),
        )

        monitor_button_frame = ctk.CTkFrame(
            monitor_frame,
            fg_color="transparent",
        )
        monitor_button_frame.pack(
            fill="x",
            padx=18,
            pady=(0, 8),
        )

        self.monitor_start_button = ctk.CTkButton(
            monitor_button_frame,
            text="監視開始",
            width=130,
            command=self.start_monitoring,
        )
        self.monitor_start_button.pack(
            side="left",
        )

        self.monitor_stop_button = ctk.CTkButton(
            monitor_button_frame,
            text="監視停止",
            width=130,
            command=self.stop_monitoring,
            state="disabled",
        )
        self.monitor_stop_button.pack(
            side="left",
            padx=(10, 0),
        )

        self.monitor_status_label = ctk.CTkLabel(
            monitor_frame,
            text="停止中",
            anchor="w",
        )
        self.monitor_status_label.pack(
            fill="x",
            padx=18,
            pady=(0, 16),
        )

        stats = ctk.CTkFrame(
            self,
        )
        stats.pack(
            fill="x",
            padx=24,
            pady=(0, 16),
        )

        self.total_coins_label = ctk.CTkLabel(
            stats,
            text="合計コイン: 0",
            font=ctk.CTkFont(
                size=22,
                weight="bold",
            ),
        )
        self.total_coins_label.pack(
            side="left",
            padx=20,
            pady=18,
        )

        self.count_label = ctk.CTkLabel(
            stats,
            text="検出件数: 0",
            font=ctk.CTkFont(
                size=18,
            ),
        )
        self.count_label.pack(
            side="left",
            padx=20,
            pady=18,
        )

        list_title = ctk.CTkLabel(
            self,
            text="ギフト履歴",
            font=ctk.CTkFont(
                size=20,
                weight="bold",
            ),
        )
        list_title.pack(
            anchor="w",
            padx=24,
            pady=(0, 8),
        )

        self.history_list = ctk.CTkScrollableFrame(
            self,
        )
        self.history_list.pack(
            fill="both",
            expand=True,
            padx=24,
            pady=(0, 24),
        )

    def start_monitoring(self):
        if self.monitoring:
            return

        if self.obs is None or not self.obs.is_connected():
            messagebox.showwarning(
                "ギフト監視",
                "OBSに接続されていません。",
            )
            return

        started = self.monitor_worker.start()

        if not started:
            self.monitor_status_label.configure(
                text=(
                    "監視を開始できません。"
                    " 前回の停止処理中か、"
                    "OBS接続を確認してください。"
                )
            )
            return

        self.monitoring = True

        self.monitor_start_button.configure(
            state="disabled"
        )
        self.monitor_stop_button.configure(
            state="normal"
        )

        self.analyze_button.configure(
            state="disabled"
        )
        self.obs_analyze_button.configure(
            state="disabled"
        )

        self.monitor_status_label.configure(
            text="監視中 / OBSを1秒間隔で取得しています"
        )

        self._schedule_monitor_event_poll()

    def stop_monitoring(self):
        if not self.monitoring:
            return

        self.monitoring = False

        self.monitor_worker.stop(
            wait=False
        )

        self.monitor_start_button.configure(
            state="normal"
        )
        self.monitor_stop_button.configure(
            state="disabled"
        )

        self.obs_analyze_button.configure(
            state="normal"
        )

        self.analyze_button.configure(
            state=(
                "normal"
                if self.selected_image_path
                else "disabled"
            )
        )

        self.monitor_status_label.configure(
            text="停止中"
        )

    def _schedule_monitor_event_poll(self):
        if self.monitor_after_id is not None:
            return

        self.monitor_after_id = self.after(
            250,
            self._poll_monitor_events,
        )

    def _poll_monitor_events(self):
        self.monitor_after_id = None

        for _ in range(200):
            event = (
                self.monitor_worker.get_event_nowait()
            )

            if event is None:
                break

            self._handle_monitor_event(
                event
            )

        if self.monitoring:
            self._schedule_monitor_event_poll()

    def _handle_monitor_event(
        self,
        event,
    ):
        event_type = event.get(
            "type"
        )

        if event_type == "analysis_result":
            result = event.get(
                "result"
            ) or {}

            if result.get("analyzed"):
                analysis = result.get(
                    "analysis"
                ) or {}

                counted = analysis.get(
                    "counted_detections"
                ) or []

                total_coins = analysis.get(
                    "total_coins",
                    0,
                ) or 0

                backlog = event.get(
                    "backlog",
                    0,
                )

                pending = event.get(
                    "pending_count",
                    0,
                )

                self.monitor_status_label.configure(
                    text=(
                        f"監視中 / AI分析完了: "
                        f"{len(counted)}件"
                        f" / +{total_coins:,} coins"
                        f" / 待機 {backlog}件"
                        f" / 保留 {pending}件"
                    )
                )

                self.load_history()

            elif result.get(
                "blocked_by_rate_limit"
            ):
                retry_after = result.get(
                    "retry_after_seconds",
                    0.0,
                )

                pending = event.get(
                    "pending_count",
                    0,
                )

                self.monitor_status_label.configure(
                    text=(
                        "監視中 / AIレート制限"
                        f" / 約{retry_after:.0f}秒後に再試行"
                        f" / 保留 {pending}件"
                    )
                )

        elif event_type == "pending_result":
            result = event.get(
                "result"
            ) or {}

            analysis = result.get(
                "analysis"
            ) or {}

            counted = analysis.get(
                "counted_detections"
            ) or []

            total_coins = analysis.get(
                "total_coins",
                0,
            ) or 0

            pending = event.get(
                "pending_count",
                0,
            )

            self.monitor_status_label.configure(
                text=(
                    "監視中 / 保留画像を分析"
                    f": {len(counted)}件"
                    f" / +{total_coins:,} coins"
                    f" / 残り {pending}件"
                )
            )

            self.load_history()

        elif event_type == "capture_backlog_overflow":
            backlog = event.get(
                "backlog",
                0,
            )

            self.monitor_status_label.configure(
                text=(
                    "監視中 / 処理遅延あり"
                    f" / 待機 {backlog}件"
                    " / 古いフレームを整理しました"
                )
            )

        elif event_type in {
            "capture_error",
            "analysis_error",
            "pending_error",
        }:
            error = event.get(
                "error",
                "unknown error",
            )

            self.monitor_status_label.configure(
                text=(
                    "監視中 / エラー: "
                    f"{error}"
                )
            )

    def destroy(self):
        self.monitoring = False

        if self.monitor_after_id is not None:
            try:
                self.after_cancel(
                    self.monitor_after_id
                )
            except Exception:
                pass

            self.monitor_after_id = None

        try:
            if hasattr(
                self,
                "monitor_worker",
            ):
                self.monitor_worker.shutdown(
                    wait=False
                )
        except Exception:
            pass

        super().destroy()

    def select_image(self):
        image_path = filedialog.askopenfilename(
            title="分析する画像を選択",
            filetypes=[
                (
                    "画像ファイル",
                    "*.png *.jpg *.jpeg *.webp",
                ),
                (
                    "すべてのファイル",
                    "*.*",
                ),
            ],
        )

        if not image_path:
            return

        self.selected_image_path = image_path

        self.selected_image_label.configure(
            text=Path(image_path).name
        )

        self.analysis_status_label.configure(
            text="分析できます。"
        )

        self.analyze_button.configure(
            state="normal"
        )

    def start_obs_analysis(self):
        if self.obs is None or not self.obs.is_connected():
            messagebox.showwarning(
                "ギフト分析",
                "OBSに接続されていません。",
            )
            return

        scene = self.obs.get_current_scene()

        if not scene:
            messagebox.showerror(
                "ギフト分析",
                "現在のOBSシーンを取得できませんでした。",
            )
            return

        screenshot_path = "images/current.png"

        result = self.obs.save_screenshot(
            scene,
            screenshot_path,
        )

        if not result:
            messagebox.showerror(
                "ギフト分析",
                "OBSスクリーンショットの取得に失敗しました。",
            )
            return

        resolved_path = self.obs.resolve_screenshot_path(
            screenshot_path
        )

        self.selected_image_path = str(
            resolved_path
        )

        self.selected_image_label.configure(
            text=Path(resolved_path).name
        )

        self.analysis_status_label.configure(
            text="OBS画像を取得しました。AI分析を開始します..."
        )

        self.start_analysis()

    def start_analysis(self):
        if not self.selected_image_path:
            messagebox.showwarning(
                "ギフト分析",
                "先に画像を選択してください。",
            )
            return

        self.analyze_button.configure(
            state="disabled"
        )

        self.analysis_status_label.configure(
            text="AIで分析中..."
        )

        thread = threading.Thread(
            target=self._run_analysis,
            daemon=True,
        )
        thread.start()

    def _run_analysis(self):
        try:
            result = self.analyzer.analyze_image(
                self.selected_image_path
            )

            self.after(
                0,
                lambda: self._analysis_finished(
                    result
                ),
            )

        except Exception as exc:
            self.after(
                0,
                lambda error=str(exc):
                self._analysis_failed(error),
            )

    def _analysis_finished(
        self,
        result,
    ):
        accepted = result.get(
            "accepted_detections",
            [],
        )

        ignored = result.get(
            "ignored_detections",
            [],
        )

        total_coins = result.get(
            "total_coins",
            0,
        )

        unknown_count = result.get(
            "unknown_count",
            0,
        )

        if accepted:
            text = (
                f"分析完了: {len(accepted)}件検出"
                f" / {total_coins:,} coins"
            )

            if unknown_count:
                text += (
                    f" / 未知ギフト {unknown_count}件"
                )
        else:
            text = "分析完了: ギフトは検出されませんでした。"

            if ignored:
                text += (
                    f" 低信頼度 {len(ignored)}件"
                )

        self.analysis_status_label.configure(
            text=text
        )

        self.analyze_button.configure(
            state="normal"
        )

        self.load_history()

    def _analysis_failed(
        self,
        error,
    ):
        self.analysis_status_label.configure(
            text="分析に失敗しました。"
        )

        self.analyze_button.configure(
            state="normal"
        )

        messagebox.showerror(
            "ギフト分析エラー",
            error,
        )

    def load_history(self):
        try:
            rows = self.history.get_gift_history(
                limit=self.HISTORY_LIMIT
            )

            total_coins = (
                self.history.get_gift_total_coins()
            )

        except Exception as exc:
            self.total_coins_label.configure(
                text="合計コイン: 読み込みエラー"
            )

            self.count_label.configure(
                text=f"エラー: {exc}"
            )

            return

        self.total_coins_label.configure(
            text=f"合計コイン: {total_coins:,}"
        )

        self.count_label.configure(
            text=f"検出件数: {len(rows)}"
        )

        for widget in (
            self.history_list.winfo_children()
        ):
            widget.destroy()

        if not rows:
            empty_label = ctk.CTkLabel(
                self.history_list,
                text="まだギフト履歴はありません。",
                font=ctk.CTkFont(
                    size=16,
                ),
            )
            empty_label.pack(
                pady=30,
            )
            return

        for row in rows:
            self._create_history_item(
                row
            )

    def _create_history_item(
        self,
        row,
    ):
        (
            history_id,
            created_at,
            gift_id,
            gift_name,
            quantity,
            coins_each,
            total_coins,
            confidence,
            is_known,
            image_path,
        ) = row

        frame = ctk.CTkFrame(
            self.history_list,
        )
        frame.pack(
            fill="x",
            padx=4,
            pady=5,
        )

        if is_known:
            display_name = (
                gift_name
                or gift_id
            )
            status = "認識済み"
        else:
            display_name = (
                gift_name
                or gift_id
                or "unknown"
            )
            status = "未知ギフト"

        if total_coins is None:
            coin_text = "-"
        else:
            coin_text = (
                f"{total_coins:,} coins"
            )

        if confidence is None:
            confidence_text = "-"
        else:
            confidence_text = (
                f"{confidence:.0%}"
            )

        name_label = ctk.CTkLabel(
            frame,
            text=(
                f"{display_name}"
                f"  ×{quantity}"
            ),
            font=ctk.CTkFont(
                size=17,
                weight="bold",
            ),
        )
        name_label.pack(
            anchor="w",
            padx=14,
            pady=(10, 2),
        )

        detail_label = ctk.CTkLabel(
            frame,
            text=(
                f"{coin_text}"
                f"   |   信頼度 {confidence_text}"
                f"   |   {status}"
                f"   |   {created_at}"
            ),
            font=ctk.CTkFont(
                size=13,
            ),
        )
        detail_label.pack(
            anchor="w",
            padx=14,
            pady=(0, 10),
        )
