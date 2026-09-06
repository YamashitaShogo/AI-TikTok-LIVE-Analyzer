import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.gift_analyzer import GiftAnalyzer
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
