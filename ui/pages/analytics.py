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
        self.configure(fg_color=("#F6F8FC", "#0B1120"))
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=28,
            pady=(24, 12),
        )
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            title_box,
            text="Analytics",
            font=("Yu Gothic UI", 28, "bold"),
            text_color=("#111827", "#F8FAFC"),
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_box,
            text="AI分析結果の傾向とスコア推移を確認できます。",
            font=("Yu Gothic UI", 12),
            text_color=("#64748B", "#94A3B8"),
        ).pack(anchor="w", pady=(2, 0))

        ctk.CTkButton(
            header,
            text="↻  更新",
            width=108,
            height=38,
            corner_radius=10,
            fg_color=("#FFFFFF", "#111827"),
            hover_color=("#EEF2FF", "#1E293B"),
            text_color=("#3157D5", "#AFC0FF"),
            border_width=1,
            border_color=("#D9E0F0", "#334155"),
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
            padx=28,
            pady=(0, 24),
        )
        body.grid_columnconfigure(0, weight=1)

        self._build_summary(body)
        self._build_graph(body)
        self._build_rankings(body)

    def _build_summary(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 14))

        for column in range(5):
            frame.grid_columnconfigure(column, weight=1)

        self.total_value = self._create_card(
            frame, 0, "総分析回数", "0回", "分析した累計回数"
        )
        self.average_value = self._create_card(
            frame, 1, "平均スコア", "0点", "全履歴の平均"
        )
        self.max_value = self._create_card(
            frame, 2, "最高スコア", "0点", "これまでの最高"
        )
        self.min_value = self._create_card(
            frame, 3, "最低スコア", "0点", "改善余地の目安"
        )
        self.today_value = self._create_card(
            frame, 4, "今日の分析", "0回", "本日の実行回数"
        )

    def _create_card(self, parent, column, title, value, caption):
        card = ctk.CTkFrame(
            parent,
            corner_radius=16,
            fg_color=("#FFFFFF", "#111827"),
            border_width=1,
            border_color=("#E6EAF2", "#243047"),
        )
        card.grid(
            row=0,
            column=column,
            sticky="nsew",
            padx=5,
        )

        ctk.CTkLabel(
            card,
            text=title,
            font=("Yu Gothic UI", 12, "bold"),
            text_color=("#64748B", "#94A3B8"),
        ).pack(anchor="w", padx=16, pady=(14, 1))

        label = ctk.CTkLabel(
            card,
            text=value,
            font=("Yu Gothic UI", 26, "bold"),
            text_color=("#172033", "#F8FAFC"),
        )
        label.pack(anchor="w", padx=16)

        ctk.CTkLabel(
            card,
            text=caption,
            font=("Yu Gothic UI", 10),
            text_color=("#94A3B8", "#64748B"),
        ).pack(anchor="w", padx=16, pady=(0, 14))

        return label

    def _build_graph(self, parent):
        frame = ctk.CTkFrame(
            parent,
            corner_radius=18,
            fg_color=("#FFFFFF", "#111827"),
            border_width=1,
            border_color=("#E6EAF2", "#243047"),
        )
        frame.grid(row=1, column=0, sticky="ew", pady=(0, 14))

        heading = ctk.CTkFrame(frame, fg_color="transparent")
        heading.pack(fill="x", padx=18, pady=(16, 8))

        ctk.CTkLabel(
            heading,
            text=f"スコア推移",
            font=("Yu Gothic UI", 18, "bold"),
            text_color=("#172033", "#F8FAFC"),
        ).pack(side="left")

        ctk.CTkLabel(
            heading,
            text=f"直近{self.GRAPH_LIMIT}回",
            font=("Yu Gothic UI", 11, "bold"),
            text_color=("#4565D8", "#AFC0FF"),
            fg_color=("#EEF2FF", "#1C2A4A"),
            corner_radius=8,
        ).pack(side="left", padx=(10, 0), ipadx=8, ipady=3)

        self.graph_canvas = ctk.CTkCanvas(
            frame,
            height=320,
            highlightthickness=0,
            bg="#111827",
        )
        self.graph_canvas.pack(
            fill="x",
            expand=True,
            padx=18,
            pady=(0, 18),
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

        high_frame = ctk.CTkFrame(
            frame,
            corner_radius=18,
            fg_color=("#FFFFFF", "#111827"),
            border_width=1,
            border_color=("#E6EAF2", "#243047"),
        )
        high_frame.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 7),
        )

        ctk.CTkLabel(
            high_frame,
            text="高得点ランキング",
            font=("Yu Gothic UI", 18, "bold"),
            text_color=("#172033", "#F8FAFC"),
        ).pack(anchor="w", padx=18, pady=(16, 8))

        ctk.CTkLabel(
            high_frame,
            text="成果が出ている分析結果",
            font=("Yu Gothic UI", 11),
            text_color=("#64748B", "#94A3B8"),
        ).pack(anchor="w", padx=18, pady=(0, 10))

        self.high_text = ctk.CTkTextbox(
            high_frame,
            height=260,
            wrap="word",
            corner_radius=12,
            fg_color=("#F8FAFC", "#0F172A"),
            border_width=1,
            border_color=("#E6EAF2", "#243047"),
            text_color=("#334155", "#E2E8F0"),
        )
        self.high_text.pack(
            fill="both",
            expand=True,
            padx=18,
            pady=(0, 18),
        )

        low_frame = ctk.CTkFrame(
            frame,
            corner_radius=18,
            fg_color=("#FFFFFF", "#111827"),
            border_width=1,
            border_color=("#E6EAF2", "#243047"),
        )
        low_frame.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(7, 0),
        )

        ctk.CTkLabel(
            low_frame,
            text="改善優先ランキング",
            font=("Yu Gothic UI", 18, "bold"),
            text_color=("#172033", "#F8FAFC"),
        ).pack(anchor="w", padx=18, pady=(16, 8))

        ctk.CTkLabel(
            low_frame,
            text="優先して見直したい分析結果",
            font=("Yu Gothic UI", 11),
            text_color=("#64748B", "#94A3B8"),
        ).pack(anchor="w", padx=18, pady=(0, 10))

        self.low_text = ctk.CTkTextbox(
            low_frame,
            height=260,
            wrap="word",
            corner_radius=12,
            fg_color=("#F8FAFC", "#0F172A"),
            border_width=1,
            border_color=("#E6EAF2", "#243047"),
            text_color=("#334155", "#E2E8F0"),
        )
        self.low_text.pack(
            fill="both",
            expand=True,
            padx=18,
            pady=(0, 18),
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
                fill="#334155",
            )
            canvas.create_text(
                left - 8,
                y,
                text=str(value),
                fill="#94A3B8",
                anchor="e",
                font=("Yu Gothic UI", 9),
            )

        if not scores:
            canvas.create_text(
                width / 2,
                height / 2,
                text="分析履歴がありません",
                fill="#94A3B8",
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
                fill="#4F6FEA",
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
                outline="#4F6FEA",
                width=2,
            )

            if len(scores) <= 12 or index in (1, len(scores)):
                canvas.create_text(
                    x,
                    height - 13,
                    text=str(index),
                    fill="#94A3B8",
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
