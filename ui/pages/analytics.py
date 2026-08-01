import customtkinter as ctk

from core.history import HistoryDB


class AnalyticsPage(ctk.CTkFrame):
    """AI分析履歴を可視化する分析ページ。"""

    GRAPH_LIMIT = 30
    REFRESH_INTERVAL_MS = 5000

    def __init__(self, parent):
        super().__init__(parent)

        self.history = HistoryDB()
        self._destroying = False
        self._refresh_job = None
        self._rows = []

        self._build_ui()
        self.refresh()
        self._start_auto_refresh()

    # ==================================================
    # UI
    # ==================================================

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=20,
            pady=(18, 8),
        )
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="📈 分析レポート",
            font=("Yu Gothic UI", 24, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            header,
            text="🔄 更新",
            width=110,
            command=self.refresh,
        ).grid(row=0, column=1, sticky="e")

        body = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
        )
        body.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=20,
            pady=(0, 18),
        )
        body.grid_columnconfigure(0, weight=1)

        self._build_summary(body)
        self._build_graph(body)
        self._build_rankings(body)

    def _build_summary(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        for column in range(5):
            frame.grid_columnconfigure(column, weight=1)

        self.total_value = self._create_card(
            frame, 0, "総分析回数", "0回"
        )
        self.average_value = self._create_card(
            frame, 1, "平均スコア", "0点"
        )
        self.max_value = self._create_card(
            frame, 2, "最高スコア", "0点"
        )
        self.min_value = self._create_card(
            frame, 3, "最低スコア", "0点"
        )
        self.today_value = self._create_card(
            frame, 4, "今日の分析", "0回"
        )

    def _create_card(self, parent, column, title, value):
        card = ctk.CTkFrame(parent, corner_radius=12)
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

        label = ctk.CTkLabel(
            card,
            text=value,
            font=("Yu Gothic UI", 25, "bold"),
        )
        label.pack(pady=(0, 12))

        return label

    def _build_graph(self, parent):
        frame = ctk.CTkFrame(parent)
        frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        ctk.CTkLabel(
            frame,
            text=f"📊 直近{self.GRAPH_LIMIT}回のスコア推移",
            font=("Yu Gothic UI", 18, "bold"),
        ).pack(anchor="w", padx=15, pady=(12, 6))

        self.graph_canvas = ctk.CTkCanvas(
            frame,
            height=320,
            highlightthickness=0,
            bg="#242424",
        )
        self.graph_canvas.pack(
            fill="x",
            expand=True,
            padx=15,
            pady=(0, 15),
        )
        self.graph_canvas.bind(
            "<Configure>",
            lambda _event: self._draw_graph(),
        )

    def _build_rankings(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=2, column=0, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)

        high_frame = ctk.CTkFrame(frame)
        high_frame.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 5),
        )

        ctk.CTkLabel(
            high_frame,
            text="🏆 高得点ランキング",
            font=("Yu Gothic UI", 18, "bold"),
        ).pack(anchor="w", padx=15, pady=(12, 6))

        self.high_text = ctk.CTkTextbox(
            high_frame,
            height=260,
            wrap="word",
        )
        self.high_text.pack(
            fill="both",
            expand=True,
            padx=15,
            pady=(0, 15),
        )

        low_frame = ctk.CTkFrame(frame)
        low_frame.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(5, 0),
        )

        ctk.CTkLabel(
            low_frame,
            text="💡 改善優先ランキング",
            font=("Yu Gothic UI", 18, "bold"),
        ).pack(anchor="w", padx=15, pady=(12, 6))

        self.low_text = ctk.CTkTextbox(
            low_frame,
            height=260,
            wrap="word",
        )
        self.low_text.pack(
            fill="both",
            expand=True,
            padx=15,
            pady=(0, 15),
        )

    # ==================================================
    # Data refresh
    # ==================================================

    def refresh(self):
        if self._destroying:
            return

        try:
            self._rows = self.history.get_all() or []

            total = self.history.get_count()
            average = self.history.get_average()
            maximum = self.history.get_max()
            minimum = self.history.get_min()
            today = self.history.get_today_count()

            self.total_value.configure(
                text=f"{self._display(total)}回"
            )
            self.average_value.configure(
                text=f"{self._display(average)}点"
            )
            self.max_value.configure(
                text=f"{self._display(maximum)}点"
            )
            self.min_value.configure(
                text=f"{self._display(minimum)}点"
            )
            self.today_value.configure(
                text=f"{self._display(today)}回"
            )

            self._draw_graph()
            self._update_rankings()

        except Exception as exc:
            self._set_textbox(
                self.high_text,
                f"分析データの取得に失敗しました。\n\n{exc}",
            )
            self._set_textbox(
                self.low_text,
                f"分析データの取得に失敗しました。\n\n{exc}",
            )

    def _update_rankings(self):
        valid_rows = []

        for row in self._rows:
            if len(row) < 5:
                continue

            score = self._safe_score(row[2])
            if score is None:
                continue

            valid_rows.append(
                {
                    "id": row[0],
                    "date": row[1],
                    "score": score,
                    "result": row[4] or "",
                }
            )

        if not valid_rows:
            self._set_textbox(
                self.high_text,
                "まだ分析履歴がありません。",
            )
            self._set_textbox(
                self.low_text,
                "まだ分析履歴がありません。",
            )
            return

        high_rows = sorted(
            valid_rows,
            key=lambda item: item["score"],
            reverse=True,
        )[:5]

        low_rows = sorted(
            valid_rows,
            key=lambda item: item["score"],
        )[:5]

        high_lines = []
        for index, item in enumerate(high_rows, start=1):
            preview = self._result_preview(item["result"])
            high_lines.append(
                f"{index}位　{item['score']:g}点\n"
                f"{item['date']}\n"
                f"{preview}\n"
            )

        low_lines = []
        for index, item in enumerate(low_rows, start=1):
            preview = self._result_preview(item["result"])
            low_lines.append(
                f"{index}位　{item['score']:g}点\n"
                f"{item['date']}\n"
                f"{preview}\n"
            )

        self._set_textbox(
            self.high_text,
            "\n".join(high_lines),
        )
        self._set_textbox(
            self.low_text,
            "\n".join(low_lines),
        )

    # ==================================================
    # Graph
    # ==================================================

    def _draw_graph(self):
        if self._destroying:
            return

        canvas = self.graph_canvas
        canvas.delete("all")

        width = max(canvas.winfo_width(), 600)
        height = max(canvas.winfo_height(), 300)

        left = 45
        right = 20
        top = 20
        bottom = 35

        plot_width = width - left - right
        plot_height = height - top - bottom

        scores = []

        for row in reversed(self._rows[:self.GRAPH_LIMIT]):
            if len(row) <= 2:
                continue

            score = self._safe_score(row[2])
            if score is not None:
                scores.append(score)

        for value in (0, 25, 50, 75, 100):
            y = top + plot_height * (1 - value / 100)

            canvas.create_line(
                left,
                y,
                width - right,
                y,
                fill="#4A4A4A",
            )
            canvas.create_text(
                left - 8,
                y,
                text=str(value),
                fill="#CCCCCC",
                anchor="e",
                font=("Yu Gothic UI", 9),
            )

        if not scores:
            canvas.create_text(
                width / 2,
                height / 2,
                text="分析履歴がありません",
                fill="#BBBBBB",
                font=("Yu Gothic UI", 15),
            )
            return

        if len(scores) == 1:
            x_values = [left + plot_width / 2]
        else:
            x_values = [
                left + plot_width * index / (len(scores) - 1)
                for index in range(len(scores))
            ]

        coordinates = []

        for x, score in zip(x_values, scores):
            y = top + plot_height * (1 - score / 100)
            coordinates.extend([x, y])

        if len(scores) >= 2:
            canvas.create_line(
                *coordinates,
                fill="#3B8ED0",
                width=3,
                smooth=True,
            )

        for index, (x, score) in enumerate(
            zip(x_values, scores),
            start=1,
        ):
            y = top + plot_height * (1 - score / 100)

            canvas.create_oval(
                x - 4,
                y - 4,
                x + 4,
                y + 4,
                fill="#FFFFFF",
                outline="#3B8ED0",
                width=2,
            )

            if len(scores) <= 12 or index in (1, len(scores)):
                canvas.create_text(
                    x,
                    height - 13,
                    text=str(index),
                    fill="#BBBBBB",
                    font=("Yu Gothic UI", 9),
                )

    # ==================================================
    # Auto refresh
    # ==================================================

    def _start_auto_refresh(self):
        if self._destroying:
            return

        self._refresh_job = self.after(
            self.REFRESH_INTERVAL_MS,
            self._auto_refresh,
        )

    def _auto_refresh(self):
        if self._destroying:
            return

        self.refresh()
        self._start_auto_refresh()

    # ==================================================
    # Helpers
    # ==================================================

    @staticmethod
    def _safe_score(value):
        try:
            score = float(value)
        except (TypeError, ValueError):
            return None

        return max(0.0, min(100.0, score))

    @staticmethod
    def _display(value):
        return 0 if value is None else value

    @staticmethod
    def _result_preview(text):
        cleaned = " ".join(str(text).split())

        if not cleaned:
            return "分析結果なし"

        if len(cleaned) > 100:
            return cleaned[:100] + "..."

        return cleaned

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

        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except Exception:
                pass

            self._refresh_job = None

        super().destroy()
