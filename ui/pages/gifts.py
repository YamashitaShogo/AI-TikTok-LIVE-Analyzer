import customtkinter as ctk

from core.history import HistoryDB


class GiftPage(ctk.CTkFrame):
    """ギフト検出履歴ページ。"""

    HISTORY_LIMIT = 100

    def __init__(self, master):
        super().__init__(master)

        self.history = HistoryDB()

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
