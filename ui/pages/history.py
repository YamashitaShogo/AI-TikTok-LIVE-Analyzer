import csv
from datetime import datetime
from pathlib import Path
import customtkinter as ctk
from PIL import Image
from tkinter import filedialog, messagebox
from typing import Optional

from core.history import HistoryDB


class HistoryPage(ctk.CTkFrame):
    """AI分析履歴ページ完成版。"""

    AUTO_REFRESH_MS = 3000

    def __init__(self, parent):
        super().__init__(parent)

        self.history = HistoryDB()

        self._destroying = False
        self._refresh_job = None
        self._selected_id: Optional[int] = None
        self._follow_latest = True
        self._rows = []
        self._history_cards = {}
        self._history_thumb_images = {}
        self._display_limit = 10
        self._display_step = 10

        self._build_ui()
        self.load_history()
        self._start_auto_refresh()

    # ==================================================
    # UI
    # ==================================================

    def _build_ui(self):
        """Build the redesigned history page without changing existing behavior."""
        # Page palette
        self.configure(fg_color=("#F5F7FC", "#0B1120"))

        page = ctk.CTkFrame(self, fg_color="transparent")
        page.pack(fill="both", expand=True, padx=22, pady=(18, 18))

        # --------------------------------------------------
        # Header
        # --------------------------------------------------
        header = ctk.CTkFrame(page, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))

        title_area = ctk.CTkFrame(header, fg_color="transparent")
        title_area.pack(side="left", fill="x", expand=True)

        title_row = ctk.CTkFrame(title_area, fg_color="transparent")
        title_row.pack(anchor="w")

        ctk.CTkLabel(
            title_row,
            text="▣  AI分析履歴",
            text_color=("#0F172A", "#F8FAFC"),
            font=("Yu Gothic UI", 26, "bold"),
        ).pack(side="left")

        self.count_label = ctk.CTkLabel(
            title_row,
            text="0件",
            text_color="#64748B",
            font=("Yu Gothic UI", 14),
        )
        self.count_label.pack(side="left", padx=(16, 0), pady=(6, 0))

        ctk.CTkLabel(
            title_area,
            text="過去に実行したAI分析の履歴と詳細を確認できます。",
            text_color="#64748B",
            font=("Yu Gothic UI", 12),
        ).pack(anchor="w", pady=(2, 0))

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.pack(side="right", padx=(12, 0))

        self.delete_all_button = ctk.CTkButton(
            actions,
            text="🗑 全件削除",
            width=118,
            height=36,
            corner_radius=9,
            fg_color="#FFF1F2",
            hover_color="#FFE4E6",
            text_color="#E11D48",
            border_width=1,
            border_color="#FB7185",
            command=self.delete_all,
        )
        self.delete_all_button.pack(side="left", padx=(0, 8))

        self.pdf_button = ctk.CTkButton(
            actions,
            text="▣ PDF出力",
            width=112,
            height=36,
            corner_radius=9,
            fg_color=("#FFFFFF", "#111827"),
            hover_color="#EFF6FF",
            text_color="#2563EB",
            border_width=1,
            border_color="#93C5FD",
            command=self.export_pdf,
        )
        self.pdf_button.pack(side="left", padx=(0, 8))

        self.export_button = ctk.CTkButton(
            actions,
            text="▤ CSV出力",
            width=112,
            height=36,
            corner_radius=9,
            fg_color=("#FFFFFF", "#111827"),
            hover_color="#EFF6FF",
            text_color="#2563EB",
            border_width=1,
            border_color="#93C5FD",
            command=self.export_csv,
        )
        self.export_button.pack(side="left", padx=(0, 8))

        self.refresh_button = ctk.CTkButton(
            actions,
            text="↻ 更新",
            width=100,
            height=36,
            corner_radius=9,
            fg_color=("#FFFFFF", "#111827"),
            hover_color="#EFF6FF",
            text_color="#2563EB",
            border_width=1,
            border_color="#93C5FD",
            command=self.load_history,
        )
        self.refresh_button.pack(side="left")

        # --------------------------------------------------
        # Two-column content
        # --------------------------------------------------
        body = ctk.CTkFrame(page, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=5, uniform="history")
        body.grid_columnconfigure(1, weight=7, uniform="history")
        body.grid_rowconfigure(0, weight=1)

        # Left: history list card
        list_panel = ctk.CTkFrame(
            body,
            fg_color=("#FFFFFF", "#111827"),
            corner_radius=16,
            border_width=1,
            border_color=("#E5EAF2", "#243047"),
        )
        list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        list_header = ctk.CTkFrame(list_panel, fg_color="transparent")
        list_header.pack(fill="x", padx=16, pady=(15, 8))

        ctk.CTkLabel(
            list_header,
            text="▤  履歴一覧",
            text_color=("#0F172A", "#F8FAFC"),
            font=("Yu Gothic UI", 17, "bold"),
        ).pack(side="left")

        self.load_more_button = ctk.CTkButton(
            list_header,
            text="さらに表示",
            width=96,
            height=30,
            corner_radius=8,
            fg_color="#EFF6FF",
            hover_color="#DBEAFE",
            text_color="#2563EB",
            command=self.load_more,
        )
        self.load_more_button.pack(side="right")

        self.history_list = ctk.CTkScrollableFrame(
            list_panel,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=("#CBD5E1", "#475569"),
            scrollbar_button_hover_color=("#94A3B8", "#64748B"),
        )
        self.history_list.pack(
            fill="both",
            expand=True,
            padx=(10, 8),
            pady=(0, 10),
        )

        # Right: detail card
        detail_shell = ctk.CTkFrame(
            body,
            fg_color=("#FFFFFF", "#111827"),
            corner_radius=16,
            border_width=1,
            border_color=("#E5EAF2", "#243047"),
        )
        detail_shell.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        detail_shell.grid_rowconfigure(1, weight=1)
        detail_shell.grid_columnconfigure(0, weight=1)

        detail_header = ctk.CTkFrame(detail_shell, fg_color="transparent")
        detail_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(15, 8))

        ctk.CTkLabel(
            detail_header,
            text="▣  分析詳細",
            text_color=("#0F172A", "#F8FAFC"),
            font=("Yu Gothic UI", 17, "bold"),
        ).pack(side="left")

        self.delete_one_button = ctk.CTkButton(
            detail_header,
            text="🗑 この履歴を削除",
            width=142,
            height=32,
            corner_radius=8,
            fg_color="#E11D48",
            hover_color="#BE123C",
            state="disabled",
            command=self.delete_selected,
        )
        self.delete_one_button.pack(side="right")

        detail_panel = ctk.CTkScrollableFrame(
            detail_shell,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=("#CBD5E1", "#475569"),
            scrollbar_button_hover_color=("#94A3B8", "#64748B"),
        )
        detail_panel.grid(row=1, column=0, sticky="nsew", padx=(10, 8), pady=(0, 10))

        # Metadata summary card
        meta_card = ctk.CTkFrame(
            detail_panel,
            fg_color=("#F8FAFC", "#0F172A"),
            corner_radius=12,
            border_width=1,
            border_color=("#E2E8F0", "#334155"),
        )
        meta_card.pack(fill="x", padx=4, pady=(2, 12))

        self.meta_label = ctk.CTkLabel(
            meta_card,
            text="履歴を選択してください",
            justify="left",
            anchor="w",
            text_color=("#334155", "#CBD5E1"),
            font=("Yu Gothic UI", 13, "bold"),
        )
        self.meta_label.pack(fill="x", padx=14, pady=12)

        # Screenshot section
        ctk.CTkLabel(
            detail_panel,
            text="▧  分析時スクリーンショット",
            text_color=("#0F172A", "#F8FAFC"),
            font=("Yu Gothic UI", 14, "bold"),
        ).pack(anchor="w", padx=4, pady=(0, 6))

        self.history_image_frame = ctk.CTkFrame(
            detail_panel,
            height=270,
            fg_color=("#F8FAFC", "#0F172A"),
            corner_radius=12,
            border_width=1,
            border_color=("#E2E8F0", "#334155"),
        )
        self.history_image_frame.pack(fill="x", padx=4, pady=(0, 14))
        self.history_image_frame.pack_propagate(False)

        self.history_image_label = ctk.CTkLabel(
            self.history_image_frame,
            text="画像は保存されていません",
            text_color=("#94A3B8", "#64748B"),
            font=("Yu Gothic UI", 12),
        )
        self.history_image_label.pack(fill="both", expand=True, padx=8, pady=8)
        self._history_ctk_image = None

        # Analysis result section
        result_header = ctk.CTkFrame(detail_panel, fg_color="transparent")
        result_header.pack(fill="x", padx=4, pady=(0, 6))
        ctk.CTkLabel(
            result_header,
            text="✦  AI分析結果",
            text_color=("#0F172A", "#F8FAFC"),
            font=("Yu Gothic UI", 14, "bold"),
        ).pack(side="left")

        self.result_text = ctk.CTkTextbox(
            detail_panel,
            height=180,
            fg_color=("#FBFCFE", "#0F172A"),
            text_color=("#1E293B", "#E2E8F0"),
            corner_radius=10,
            border_width=1,
            border_color=("#E2E8F0", "#334155"),
            font=("Yu Gothic UI", 12),
            wrap="word",
        )
        self.result_text.pack(fill="x", padx=4, pady=(0, 14))
        self.result_text.configure(state="disabled")

        # Prompt section
        ctk.CTkLabel(
            detail_panel,
            text="▣  プロンプト",
            text_color=("#0F172A", "#F8FAFC"),
            font=("Yu Gothic UI", 14, "bold"),
        ).pack(anchor="w", padx=4, pady=(0, 6))

        self.prompt_text = ctk.CTkTextbox(
            detail_panel,
            height=90,
            fg_color=("#FBFCFE", "#0F172A"),
            text_color=("#334155", "#CBD5E1"),
            corner_radius=10,
            border_width=1,
            border_color=("#E2E8F0", "#334155"),
            font=("Yu Gothic UI", 12),
            wrap="word",
        )
        self.prompt_text.pack(fill="x", padx=4, pady=(0, 6))
        self.prompt_text.configure(state="disabled")

    # ==================================================
    # Load / display
    # ==================================================

    def load_history(self):
        if self._destroying:
            return

        try:
            rows = self.history.get_recent_summaries(
                limit=self._display_limit
            )
        except Exception as exc:
            self.count_label.configure(
                text="読込エラー"
            )
            self._show_text(
                self.result_text,
                f"履歴の読み込みに失敗しました。\n\n"
                f"{type(exc).__name__}: {exc}"
            )
            return

        old_ids = [row[0] for row in self._rows]
        new_ids = [row[0] for row in rows]

        self._rows = rows

        total_count = self.history.get_count()

        self.count_label.configure(
            text=(
                f"{len(rows)}\u4ef6 / "
                f"{total_count}\u4ef6"
            )
        )

        can_load_more = (
            len(rows) < total_count
            and self._display_limit < 200
        )

        self.load_more_button.configure(
            state=(
                "normal"
                if can_load_more
                else "disabled"
            )
        )

        # 内容に変化がない場合は一覧を作り直さない
        if old_ids == new_ids:
            return

        for widget in self.history_list.winfo_children():
            widget.destroy()
        self._history_cards.clear()
        self._history_thumb_images.clear()

        if not rows:
            ctk.CTkLabel(
                self.history_list,
                text="まだ履歴はありません。",
                font=("Yu Gothic UI", 14)
            ).pack(
                pady=30
            )

            self._selected_id = None
            self._clear_detail()
            return

        for row in rows:
            self._create_history_item(row)

        # 選択中の履歴が残っていれば再選択
        if self._follow_latest:
            self.show_detail(rows[0])

        elif self._selected_id in new_ids:
            selected = next(
                row for row in rows
                if row[0] == self._selected_id
            )
            self.show_detail(selected)

        else:
            self._follow_latest = True
            self.show_detail(rows[0])

    def load_more(self):
        if self._destroying:
            return

        total_count = self.history.get_count()

        if len(self._rows) >= total_count:
            return

        self._display_limit = min(
            200,
            self._display_limit
            + self._display_step,
        )

        self.load_history()

    def _show_history_image(self, image_path):
        self._history_ctk_image = None

        if not image_path:
            self.history_image_label.configure(
                text="画像は保存されていません"
            )
            return

        path = Path(image_path)

        if not path.exists():
            self.history_image_label.configure(
                text="保存画像が見つかりません"
            )
            return

        try:
            with Image.open(path) as source:
                image = source.convert("RGB").copy()

            max_width = 420
            max_height = 250

            width, height = image.size

            scale = min(
                max_width / width,
                max_height / height,
                1.0
            )

            display_width = max(
                1,
                int(width * scale)
            )
            display_height = max(
                1,
                int(height * scale)
            )

            new_image = ctk.CTkImage(
                light_image=image,
                dark_image=image,
                size=(
                    display_width,
                    display_height
                )
            )

            # 先に参照を保持する
            self._history_ctk_image = new_image

            self.history_image_label.configure(
                text="",
                image=new_image
            )

        except Exception as exc:
            print(
                f"履歴画像の表示に失敗しました: "
                f"{type(exc).__name__}: {exc}"
            )

    def _create_history_item(self, row):
        history_id = row[0]
        created_at = row[1]
        score = row[2]

        is_selected = history_id == self._selected_id
        card = ctk.CTkFrame(
            self.history_list,
            fg_color="#F8FBFF" if is_selected else "#FFFFFF",
            corner_radius=11,
            border_width=2 if is_selected else 1,
            border_color="#3B82F6" if is_selected else "#E5EAF2",
        )
        card.pack(fill="x", padx=4, pady=5)
        self._history_cards[history_id] = card

        # Compact visual marker / thumbnail
        thumb = ctk.CTkFrame(
            card,
            width=48,
            height=48,
            corner_radius=9,
            fg_color="#EEF2FF",
        )
        thumb.pack(side="left", padx=(10, 10), pady=9)
        thumb.pack_propagate(False)

        thumb_label = ctk.CTkLabel(
            thumb,
            text="AI",
            text_color="#4F46E5",
            font=("Yu Gothic UI", 12, "bold"),
        )
        thumb_label.pack(fill="both", expand=True)

        # Load thumbnail if this history has an image.
        try:
            detail = self.history.get_by_id_with_image(history_id)
            image_path = detail[5] if detail and len(detail) > 5 else None
            if image_path and Path(image_path).exists():
                with Image.open(image_path) as source:
                    image = source.convert("RGB").copy()
                    image.thumbnail((44, 44))
                thumb_image = ctk.CTkImage(
                    light_image=image,
                    dark_image=image,
                    size=image.size,
                )
                self._history_thumb_images[history_id] = thumb_image
                thumb_label.configure(text="", image=thumb_image)
        except Exception:
            pass

        score_text = "--" if score is None else str(score)

        score_label = ctk.CTkLabel(
            card,
            text=f"{score_text}点",
            text_color=("#0F172A", "#F8FAFC"),
            font=("Yu Gothic UI", 19, "bold"),
            width=68,
            anchor="w",
        )
        score_label.pack(side="left", padx=(0, 8), pady=10)

        info = ctk.CTkLabel(
            card,
            text=f"ID: {history_id}\n{created_at}",
            justify="left",
            anchor="w",
            text_color="#64748B",
            font=("Yu Gothic UI", 11),
        )
        info.pack(side="left", fill="x", expand=True, pady=10)

        open_button = ctk.CTkButton(
            card,
            text="詳細",
            width=66,
            height=30,
            corner_radius=8,
            fg_color="#EFF6FF" if not is_selected else "#3B82F6",
            hover_color="#DBEAFE" if not is_selected else "#2563EB",
            text_color="#2563EB" if not is_selected else "#FFFFFF",
            command=lambda selected=row: self.show_detail(
                selected,
                user_selected=True,
            ),
        )
        open_button.pack(side="right", padx=(8, 10), pady=10)

        # Make the card itself clickable as well.
        def _open(_event=None, selected=row):
            self.show_detail(selected, user_selected=True)

        for widget in (card, thumb, thumb_label, score_label, info):
            widget.bind("<Button-1>", _open)

    def _refresh_selected_card_style(self):
        """Update list-card highlight after the selected history changes."""
        for history_id, card in self._history_cards.items():
            selected = history_id == self._selected_id
            card.configure(
                fg_color="#F8FBFF" if selected else "#FFFFFF",
                border_width=2 if selected else 1,
                border_color="#3B82F6" if selected else "#E5EAF2",
            )

    def show_detail(
        self,
        row,
        user_selected=False,
    ):
        if self._destroying:
            return

        self._selected_id = row[0]
        self._refresh_selected_card_style()

        if user_selected:
            latest_id = (
                self._rows[0][0]
                if self._rows
                else None
            )
            self._follow_latest = (
                self._selected_id == latest_id
            )

        # 詳細表示では画像パス付きデータを取得
        detail = self.history.get_by_id_with_image(
            self._selected_id
        )

        if detail:
            created_at = detail[1]
            score = detail[2]
            prompt = detail[3] or ""
            result = detail[4] or ""
            image_path = (
                detail[5]
                if len(detail) > 5
                else None
            )
        else:
            created_at = row[1]
            score = row[2]
            prompt = row[3] if len(row) > 3 else ""
            result = row[4] if len(row) > 4 else ""
            image_path = None

        score_text = "--" if score is None else str(score)

        self.meta_label.configure(
            text=(
                f"ID：{self._selected_id}　"
                f"日時：{created_at}　"
                f"スコア：{score_text}点"
            )
        )

        self._show_history_image(
            image_path
        )

        self._show_text(
            self.prompt_text,
            prompt or "プロンプトがありません。"
        )

        self._show_text(
            self.result_text,
            result or "分析結果がありません。"
        )

        self.delete_one_button.configure(
            state="normal"
        )


    def _clear_detail(self):
        self._refresh_selected_card_style()
        self.meta_label.configure(
            text="履歴を選択してください"
        )

        self._history_ctk_image = None

        self.history_image_label.configure(
            image=None,
            text="画像は保存されていません"
        )

        self._show_text(
            self.prompt_text,
            ""
        )
        self._show_text(
            self.result_text,
            "まだ履歴はありません。"
        )
        self.delete_one_button.configure(
            state="disabled"
        )

    @staticmethod
    def _show_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    # ==================================================
    # CSV export
    # ==================================================

    def export_csv(self):
        if self._destroying:
            return

        export_rows = self.history.get_all()

        if not export_rows:
            messagebox.showinfo(
                "CSV出力",
                "出力する履歴がありません。"
            )
            return

        default_name = (
            "analysis_history_"
            f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"
        )

        file_path = filedialog.asksaveasfilename(
            title="AI分析履歴をCSVで保存",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[
                ("CSVファイル", "*.csv"),
                ("すべてのファイル", "*.*")
            ]
        )

        if not file_path:
            return

        try:
            with open(
                file_path,
                "w",
                newline="",
                encoding="utf-8-sig"
            ) as csv_file:
                writer = csv.writer(csv_file)

                writer.writerow([
                    "ID",
                    "日時",
                    "スコア",
                    "プロンプト",
                    "AI分析結果"
                ])

                for row in export_rows:
                    history_id = row[0] if len(row) > 0 else ""
                    created_at = row[1] if len(row) > 1 else ""
                    score = row[2] if len(row) > 2 else ""
                    prompt = row[3] if len(row) > 3 else ""
                    result = row[4] if len(row) > 4 else ""

                    writer.writerow([
                        history_id,
                        created_at,
                        score,
                        prompt,
                        result
                    ])

            messagebox.showinfo(
                "CSV出力完了",
                "AI分析履歴を保存しました。\n\n"
                f"{file_path}"
            )

        except Exception as exc:
            messagebox.showerror(
                "CSV出力エラー",
                f"{type(exc).__name__}: {exc}"
            )

    # ==================================================
    # PDF export
    # ==================================================

    def export_pdf(self):
        if self._destroying:
            return

        export_rows = self.history.get_all()

        if not export_rows:
            messagebox.showinfo(
                "PDF出力",
                "出力する履歴がありません。"
            )
            return

        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import (
                ParagraphStyle,
                getSampleStyleSheet
            )
            from reportlab.lib.units import mm
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.platypus import (
                PageBreak,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle
            )
        except ModuleNotFoundError:
            messagebox.showerror(
                "PDF出力",
                "PDF出力にはReportLabが必要です。\n\n"
                "VSCodeのターミナルで次を実行してください。\n"
                "python -m pip install reportlab"
            )
            return

        default_name = (
            "analysis_report_"
            f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.pdf"
        )

        file_path = filedialog.asksaveasfilename(
            title="AI分析レポートをPDFで保存",
            defaultextension=".pdf",
            initialfile=default_name,
            filetypes=[
                ("PDFファイル", "*.pdf"),
                ("すべてのファイル", "*.*")
            ]
        )

        if not file_path:
            return

        try:
            font_name = self._register_japanese_pdf_font(
                pdfmetrics,
                TTFont
            )

            styles = getSampleStyleSheet()

            title_style = ParagraphStyle(
                "JapaneseTitle",
                parent=styles["Title"],
                fontName=font_name,
                fontSize=20,
                leading=26,
                alignment=TA_CENTER,
                spaceAfter=10 * mm
            )

            heading_style = ParagraphStyle(
                "JapaneseHeading",
                parent=styles["Heading2"],
                fontName=font_name,
                fontSize=14,
                leading=19,
                spaceBefore=4 * mm,
                spaceAfter=3 * mm
            )

            body_style = ParagraphStyle(
                "JapaneseBody",
                parent=styles["BodyText"],
                fontName=font_name,
                fontSize=9,
                leading=14,
                wordWrap="CJK"
            )

            small_style = ParagraphStyle(
                "JapaneseSmall",
                parent=body_style,
                fontSize=8,
                leading=12
            )

            document = SimpleDocTemplate(
                file_path,
                pagesize=A4,
                rightMargin=15 * mm,
                leftMargin=15 * mm,
                topMargin=15 * mm,
                bottomMargin=15 * mm,
                title="Livemetry Pulse レポート",
                author="Livemetry Pulse"
            )

            story = []

            story.append(
                Paragraph(
                    "Livemetry Pulse<br/>分析レポート",
                    title_style
                )
            )
            story.append(
                Paragraph(
                    "作成日時："
                    f"{datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}",
                    body_style
                )
            )
            story.append(Spacer(1, 5 * mm))

            scores = []
            for row in export_rows:
                if len(row) <= 2:
                    continue

                try:
                    scores.append(float(row[2]))
                except (TypeError, ValueError):
                    pass

            average = (
                sum(scores) / len(scores)
                if scores
                else 0
            )
            maximum = max(scores) if scores else 0
            minimum = min(scores) if scores else 0

            summary_data = [
                [
                    Paragraph("総分析回数", body_style),
                    Paragraph("平均スコア", body_style),
                    Paragraph("最高スコア", body_style),
                    Paragraph("最低スコア", body_style)
                ],
                [
                    f"{len(export_rows)}回",
                    f"{average:.1f}点",
                    f"{maximum:g}点",
                    f"{minimum:g}点"
                ]
            ]

            summary_table = Table(
                summary_data,
                colWidths=[42 * mm] * 4,
                rowHeights=[10 * mm, 12 * mm]
            )
            summary_table.setStyle(
                TableStyle([
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9EAF7")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#777777")),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10)
                ])
            )
            story.append(summary_table)
            story.append(Spacer(1, 7 * mm))

            story.append(
                Paragraph(
                    "分析履歴一覧",
                    heading_style
                )
            )

            history_data = [[
                Paragraph("日時", small_style),
                Paragraph("スコア", small_style),
                Paragraph("AI分析結果（抜粋）", small_style)
            ]]

            for row in export_rows:
                created_at = row[1] if len(row) > 1 else ""
                score = row[2] if len(row) > 2 else ""
                result = row[4] if len(row) > 4 else ""

                preview = " ".join(str(result).split())
                if len(preview) > 170:
                    preview = preview[:170] + "..."

                history_data.append([
                    Paragraph(
                        self._escape_pdf_text(created_at),
                        small_style
                    ),
                    Paragraph(
                        self._escape_pdf_text(score),
                        small_style
                    ),
                    Paragraph(
                        self._escape_pdf_text(
                            preview or "分析結果なし"
                        ),
                        small_style
                    )
                ])

            history_table = Table(
                history_data,
                colWidths=[38 * mm, 18 * mm, 112 * mm],
                repeatRows=1
            )
            history_table.setStyle(
                TableStyle([
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9EAF7")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#888888")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (1, 1), (1, -1), "CENTER"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5)
                ])
            )
            story.append(history_table)

            for index, row in enumerate(export_rows, start=1):
                story.append(PageBreak())

                history_id = row[0] if len(row) > 0 else ""
                created_at = row[1] if len(row) > 1 else ""
                score = row[2] if len(row) > 2 else ""
                prompt = row[3] if len(row) > 3 else ""
                result = row[4] if len(row) > 4 else ""

                story.append(
                    Paragraph(
                        f"分析詳細 {index}",
                        heading_style
                    )
                )
                story.append(
                    Paragraph(
                        "ID："
                        f"{self._escape_pdf_text(history_id)}<br/>"
                        "日時："
                        f"{self._escape_pdf_text(created_at)}<br/>"
                        "スコア："
                        f"{self._escape_pdf_text(score)}点",
                        body_style
                    )
                )
                story.append(Spacer(1, 5 * mm))

                story.append(
                    Paragraph(
                        "プロンプト",
                        heading_style
                    )
                )
                story.append(
                    Paragraph(
                        self._escape_pdf_text(
                            prompt or "プロンプトなし"
                        ),
                        body_style
                    )
                )
                story.append(Spacer(1, 5 * mm))

                story.append(
                    Paragraph(
                        "AI分析結果",
                        heading_style
                    )
                )
                story.append(
                    Paragraph(
                        self._escape_pdf_text(
                            result or "分析結果なし"
                        ),
                        body_style
                    )
                )

            document.build(
                story,
                onFirstPage=self._draw_pdf_footer,
                onLaterPages=self._draw_pdf_footer
            )

            messagebox.showinfo(
                "PDF出力完了",
                "AI分析レポートを保存しました。\n\n"
                f"{file_path}"
            )

        except FileNotFoundError as exc:
            messagebox.showerror(
                "PDF出力エラー",
                str(exc)
            )
        except Exception as exc:
            messagebox.showerror(
                "PDF出力エラー",
                f"{type(exc).__name__}: {exc}"
            )

    @staticmethod
    def _register_japanese_pdf_font(pdfmetrics, TTFont):
        font_candidates = [
            Path(r"C:\Windows\Fonts\YuGothR.ttc"),
            Path(r"C:\Windows\Fonts\YuGothM.ttc"),
            Path(r"C:\Windows\Fonts\msgothic.ttc"),
            Path(r"C:\Windows\Fonts\meiryo.ttc")
        ]

        for font_path in font_candidates:
            if not font_path.exists():
                continue

            try:
                pdfmetrics.registerFont(
                    TTFont(
                        "JapaneseFont",
                        str(font_path),
                        subfontIndex=0
                    )
                )
                return "JapaneseFont"
            except Exception:
                continue

        raise FileNotFoundError(
            "日本語PDF用フォントが見つかりませんでした。\n"
            "WindowsのYu Gothic、MS Gothic、Meiryoのいずれかが必要です。"
        )

    @staticmethod
    def _escape_pdf_text(value):
        from xml.sax.saxutils import escape

        text = str(value)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return escape(text).replace("\n", "<br/>")

    @staticmethod
    def _draw_pdf_footer(canvas, document):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm

        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(
            A4[0] - 15 * mm,
            8 * mm,
            f"Page {document.page}"
        )
        canvas.restoreState()

    # ==================================================
    # Delete
    # ==================================================

    def delete_selected(self):
        if self._selected_id is None:
            return

        confirmed = messagebox.askyesno(
            "履歴削除",
            f"ID {self._selected_id} の履歴を削除しますか？"
        )

        if not confirmed:
            return

        try:
            self.history.delete(
                self._selected_id
            )
            self._selected_id = None
            self.load_history()

        except Exception as exc:
            messagebox.showerror(
                "削除エラー",
                f"{type(exc).__name__}: {exc}"
            )

    def delete_all(self):
        if not self._rows:
            messagebox.showinfo(
                "履歴削除",
                "削除する履歴がありません。"
            )
            return

        confirmed = messagebox.askyesno(
            "全履歴削除",
            "すべてのAI分析履歴を削除します。\n"
            "この操作は元に戻せません。\n\n"
            "本当に削除しますか？"
        )

        if not confirmed:
            return

        try:
            self.history.delete_all()
            self._selected_id = None
            self.load_history()

        except Exception as exc:
            messagebox.showerror(
                "削除エラー",
                f"{type(exc).__name__}: {exc}"
            )

    # ==================================================
    # Auto refresh / cleanup
    # ==================================================

    def _start_auto_refresh(self):
        if self._destroying:
            return

        self._refresh_job = self.after(
            self.AUTO_REFRESH_MS,
            self._auto_refresh
        )

    def _auto_refresh(self):
        if self._destroying:
            return

        self.load_history()
        self._start_auto_refresh()

    def destroy(self):
        if self._destroying:
            return

        self._destroying = True

        if self._refresh_job is not None:
            try:
                self.after_cancel(
                    self._refresh_job
                )
            except Exception:
                pass

            self._refresh_job = None

        super().destroy()
