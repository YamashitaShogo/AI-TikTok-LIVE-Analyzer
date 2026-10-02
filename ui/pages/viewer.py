import json
import os
import threading
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
from PIL import Image


class ViewerPage(ctk.CTkFrame):
    """TikTok Viewer / Collector status page."""

    REFRESH_MS = 2000
    ACTIVE_MAX_AGE_SECONDS = 15

    def __init__(self, parent, viewer_manager=None):
        super().__init__(
            parent,
            fg_color=("#F5F7FB", "#0B1120"),
        )

        self.viewer_manager = viewer_manager
        self._destroying = False
        self._refresh_id = None
        self._preview_image = None
        self._last_preview_mtime = None

        base = os.getenv("LOCALAPPDATA")
        if not base:
            base = os.path.join(
                os.path.expanduser("~"),
                "AppData",
                "Local",
            )

        self.capture_dir = (
            Path(base)
            / "AI-TikTok-LIVE-Analyzer"
            / "capture"
        )
        self.frame_path = self.capture_dir / "latest.jpg"
        self.payload_path = self.capture_dir / "analysis_payload.json"

        self._build_ui()
        self._refresh()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(
            self,
            corner_radius=18,
            fg_color=("#FFFFFF", "#141C2B"),
            border_width=1,
            border_color=("#E7ECF4", "#263244"),
        )
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=28,
            pady=(22, 14),
        )
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="TikTok Viewer",
            font=("Yu Gothic UI", 26, "bold"),
            text_color=("#132347", "#F8FAFC"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=22,
            pady=(18, 2),
        )

        ctk.CTkLabel(
            header,
            text="TikTok LIVEの映像とコメント取得状態を確認します。",
            font=("Yu Gothic UI", 11),
            text_color=("#71809C", "#94A3B8"),
        ).grid(
            row=1,
            column=0,
            sticky="w",
            padx=22,
            pady=(0, 18),
        )

        self.status_chip = ctk.CTkLabel(
            header,
            text="● 確認中",
            font=("Yu Gothic UI", 11, "bold"),
            text_color="#2F80ED",
        )
        self.status_chip.grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e",
            padx=22,
        )

        info = ctk.CTkFrame(
            self,
            corner_radius=18,
            fg_color=("#FFFFFF", "#141C2B"),
            border_width=1,
            border_color=("#E7ECF4", "#263244"),
        )
        info.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=28,
            pady=(0, 14),
        )

        for col in range(4):
            info.grid_columnconfigure(col, weight=1)

        self.process_value = self._make_info_card(info, 0, "Viewerプロセス", "--")
        self.frame_value = self._make_info_card(info, 1, "映像取得", "--")
        self.updated_value = self._make_info_card(info, 2, "最終更新", "--")
        self.comment_value = self._make_info_card(info, 3, "直近30秒コメント", "--")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=28,
            pady=(0, 24),
        )
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        preview_card = ctk.CTkFrame(
            body,
            corner_radius=18,
            fg_color=("#FFFFFF", "#141C2B"),
            border_width=1,
            border_color=("#E7ECF4", "#263244"),
        )
        preview_card.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 7),
        )

        ctk.CTkLabel(
            preview_card,
            text="現在取得しているLIVE映像",
            font=("Yu Gothic UI", 14, "bold"),
            text_color=("#132347", "#F8FAFC"),
        ).pack(
            anchor="w",
            padx=18,
            pady=(16, 10),
        )

        self.preview_label = ctk.CTkLabel(
            preview_card,
            text="映像待機中",
            font=("Yu Gothic UI", 12),
            text_color=("#71809C", "#94A3B8"),
        )
        self.preview_label.pack(
            fill="both",
            expand=True,
            padx=18,
            pady=(0, 18),
        )

        control_card = ctk.CTkFrame(
            body,
            corner_radius=18,
            fg_color=("#FFFFFF", "#141C2B"),
            border_width=1,
            border_color=("#E7ECF4", "#263244"),
        )
        control_card.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(7, 0),
        )

        ctk.CTkLabel(
            control_card,
            text="Viewer操作",
            font=("Yu Gothic UI", 14, "bold"),
            text_color=("#132347", "#F8FAFC"),
        ).pack(
            anchor="w",
            padx=18,
            pady=(16, 12),
        )

        self.restart_button = ctk.CTkButton(
            control_card,
            text="↻  Viewerを再起動",
            height=42,
            corner_radius=11,
            command=self._restart_viewer,
        )
        self.restart_button.pack(
            fill="x",
            padx=18,
            pady=(0, 9),
        )

        self.start_button = ctk.CTkButton(
            control_card,
            text="▶  Viewerを起動",
            height=42,
            corner_radius=11,
            command=self._start_viewer,
        )
        self.start_button.pack(
            fill="x",
            padx=18,
            pady=(0, 9),
        )

        self.stop_button = ctk.CTkButton(
            control_card,
            text="■  Viewerを停止",
            height=42,
            corner_radius=11,
            fg_color="#FFF0F3",
            hover_color="#FFE1E7",
            text_color="#E63B57",
            command=self._stop_viewer,
        )
        self.stop_button.pack(
            fill="x",
            padx=18,
            pady=(0, 12),
        )

        ctk.CTkLabel(
            control_card,
            text=(
                "映像はCollectorが5秒ごとに取得し、\n"
                "DashboardとAI分析へ渡します。"
            ),
            justify="left",
            anchor="w",
            font=("Yu Gothic UI", 10),
            text_color=("#71809C", "#94A3B8"),
        ).pack(
            fill="x",
            padx=18,
            pady=(4, 18),
        )

    def _make_info_card(self, parent, column, title, value):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(
            row=0,
            column=column,
            sticky="ew",
            padx=14,
            pady=14,
        )

        ctk.CTkLabel(
            frame,
            text=title,
            font=("Yu Gothic UI", 9, "bold"),
            text_color=("#8A97AD", "#94A3B8"),
        ).pack(anchor="w")

        label = ctk.CTkLabel(
            frame,
            text=value,
            font=("Yu Gothic UI", 15, "bold"),
            text_color=("#132347", "#F8FAFC"),
        )
        label.pack(anchor="w", pady=(4, 0))
        return label

    def _viewer_running(self):
        try:
            return bool(
                self.viewer_manager
                and self.viewer_manager.is_running()
            )
        except Exception:
            return False

    def _frame_state(self):
        try:
            if not self.frame_path.exists():
                return False, None, None

            stat = self.frame_path.stat()
            if stat.st_size <= 0:
                return False, None, None

            age = datetime.now().timestamp() - stat.st_mtime
            return (
                age <= self.ACTIVE_MAX_AGE_SECONDS,
                stat.st_mtime,
                age,
            )
        except Exception:
            return False, None, None

    def _comment_count(self):
        try:
            data = json.loads(
                self.payload_path.read_text(encoding="utf-8")
            )
            return int(data.get("comment_count", 0))
        except Exception:
            return 0

    def _refresh_preview(self, mtime):
        if not mtime:
            return
        if self._last_preview_mtime == mtime:
            return

        try:
            with Image.open(self.frame_path) as source:
                image = source.convert("RGB")
                image.thumbnail((760, 430))
                display = image.copy()

            self._preview_image = ctk.CTkImage(
                light_image=display,
                dark_image=display,
                size=display.size,
            )
            self.preview_label.configure(
                image=self._preview_image,
                text="",
            )
            self._last_preview_mtime = mtime

        except Exception as exc:
            self.preview_label.configure(
                image=None,
                text=f"プレビュー表示エラー\n{exc}",
            )

    def _refresh(self):
        if self._destroying:
            return

        running = self._viewer_running()
        active, mtime, age = self._frame_state()

        self.process_value.configure(
            text="起動中" if running else "停止中",
        )
        self.frame_value.configure(
            text="取得中" if active else "未取得",
        )

        if mtime:
            self.updated_value.configure(
                text=datetime.fromtimestamp(mtime).strftime("%H:%M:%S"),
            )
        else:
            self.updated_value.configure(text="--")

        self.comment_value.configure(
            text=f"{self._comment_count()}件",
        )

        if active:
            self.status_chip.configure(
                text="● TikTok LIVE：取得中",
                text_color="#18B981",
            )
        elif running:
            self.status_chip.configure(
                text="● Viewer起動中 / 映像待機",
                text_color="#F5A623",
            )
        else:
            self.status_chip.configure(
                text="● Viewer停止中",
                text_color="#E63B57",
            )

        self._refresh_preview(mtime)

        self._refresh_id = self.after(
            self.REFRESH_MS,
            self._refresh,
        )

    def _run_manager_action(self, action):
        def worker():
            try:
                action()
            except Exception as exc:
                print("Viewer操作エラー:", repr(exc))

        threading.Thread(
            target=worker,
            daemon=True,
        ).start()

    def _start_viewer(self):
        if self.viewer_manager is None:
            return
        self._run_manager_action(
            self.viewer_manager.start
        )

    def _stop_viewer(self):
        if self.viewer_manager is None:
            return
        self._run_manager_action(
            self.viewer_manager.stop
        )

    def _restart_viewer(self):
        if self.viewer_manager is None:
            return

        def restart():
            self.viewer_manager.stop()
            self.viewer_manager.start()

        self._run_manager_action(restart)

    def destroy(self):
        self._destroying = True

        if self._refresh_id is not None:
            try:
                self.after_cancel(self._refresh_id)
            except Exception:
                pass
            self._refresh_id = None

        super().destroy()
