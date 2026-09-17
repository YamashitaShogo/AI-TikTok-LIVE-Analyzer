from pathlib import Path

import customtkinter as ctk
from PIL import Image

from core.settings import Settings


class OBSPage(ctk.CTkFrame):
    def __init__(self, parent, obs):
        super().__init__(
            parent,
            fg_color="#F7F9FC",
        )

        self.obs = obs
        self._preview_image = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_content()
        self._load_settings()
        self.refresh_all()


    # ==================================================
    # UI
    # ==================================================

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
            text="OBS",
            font=("Yu Gothic UI", 31, "bold"),
            text_color="#132347",
        ).pack(
            anchor="w",
        )

        ctk.CTkLabel(
            title_area,
            text="\u914d\u4fe1\u306e\u4eca\u3092\u3001AI\u3067\u3055\u3089\u306b\u6df1\u304f\u3002",
            font=("Yu Gothic UI", 17, "bold"),
            text_color="#132347",
        ).pack(
            anchor="w",
            pady=(2, 0),
        )

        ctk.CTkLabel(
            title_area,
            text="OBS\u3068\u9023\u643a\u3057\u3001\u914d\u4fe1\u72b6\u614b\u30fb\u30b7\u30fc\u30f3\u30fb\u30b9\u30af\u30ea\u30fc\u30f3\u30b7\u30e7\u30c3\u30c8\u3092\u7ba1\u7406\u3057\u307e\u3059\u3002",
            font=("Yu Gothic UI", 11),
            text_color="#71809C",
        ).pack(
            anchor="w",
            pady=(4, 0),
        )

        self.header_status = ctk.CTkLabel(
            header,
            text="\u25cf  OBS \u672a\u63a5\u7d9a",
            height=36,
            corner_radius=18,
            fg_color="#F1F5F9",
            text_color="#71809C",
            font=("Yu Gothic UI", 10, "bold"),
        )
        self.header_status.grid(
            row=0,
            column=1,
            sticky="e",
        )


    def _build_content(self):
        content = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
        )
        content.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=28,
            pady=(0, 24),
        )

        content.grid_columnconfigure(
            0,
            weight=1,
        )

        self._build_status_cards(content)
        self._build_middle_area(content)
        self._build_bottom_area(content)


    def _build_status_cards(self, parent):
        row = ctk.CTkFrame(
            parent,
            fg_color="transparent",
        )
        row.grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 14),
        )

        for column in range(3):
            row.grid_columnconfigure(
                column,
                weight=1,
                uniform="status",
            )

        self.connection_value = self._status_card(
            row,
            0,
            "\u25c9",
            "OBS\u63a5\u7d9a\u30b9\u30c6\u30fc\u30bf\u30b9",
            "\u672a\u63a5\u7d9a",
            "#2F80ED",
            "#EAF3FF",
        )

        self.stream_value = self._status_card(
            row,
            1,
            "\u25b6",
            "\u914d\u4fe1\u72b6\u614b",
            "\u505c\u6b62\u4e2d",
            "#F04483",
            "#FFF0F6",
        )

        self.record_value = self._status_card(
            row,
            2,
            "\u25cf",
            "\u9332\u753b\u72b6\u614b",
            "\u505c\u6b62\u4e2d",
            "#7C5CFC",
            "#F0ECFF",
        )


    def _status_card(
        self,
        parent,
        column,
        icon,
        title,
        value,
        accent,
        soft,
    ):
        card = ctk.CTkFrame(
            parent,
            height=105,
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
                0 if column == 0 else 7,
                0 if column == 2 else 7,
            ),
        )
        card.grid_propagate(False)

        icon_box = ctk.CTkFrame(
            card,
            width=35,
            height=35,
            corner_radius=10,
            fg_color=soft,
        )
        icon_box.place(
            x=15,
            y=16,
        )
        icon_box.pack_propagate(False)

        ctk.CTkLabel(
            icon_box,
            text=icon,
            text_color=accent,
            font=("Yu Gothic UI", 15, "bold"),
        ).place(
            relx=0.5,
            rely=0.5,
            anchor="center",
        )

        ctk.CTkLabel(
            card,
            text=title,
            font=("Yu Gothic UI", 10, "bold"),
            text_color="#71809C",
        ).place(
            x=61,
            y=18,
        )

        value_label = ctk.CTkLabel(
            card,
            text=value,
            font=("Yu Gothic UI", 20, "bold"),
            text_color="#132347",
        )
        value_label.place(
            x=61,
            y=44,
        )

        return value_label


    def _build_middle_area(self, parent):
        middle = ctk.CTkFrame(
            parent,
            fg_color="transparent",
        )
        middle.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(0, 14),
        )

        middle.grid_columnconfigure(
            0,
            weight=1,
        )
        middle.grid_columnconfigure(
            1,
            weight=1,
        )

        self._build_connection_panel(middle)
        self._build_quick_panel(middle)


    def _build_connection_panel(self, parent):
        card = ctk.CTkFrame(
            parent,
            corner_radius=18,
            fg_color="#FFFFFF",
            border_width=1,
            border_color="#E7ECF4",
        )
        card.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 7),
        )

        ctk.CTkLabel(
            card,
            text="\u25c7  OBS WebSocket\u63a5\u7d9a\u8a2d\u5b9a",
            font=("Yu Gothic UI", 15, "bold"),
            text_color="#132347",
        ).pack(
            anchor="w",
            padx=18,
            pady=(16, 12),
        )

        form = ctk.CTkFrame(
            card,
            fg_color="transparent",
        )
        form.pack(
            fill="x",
            padx=18,
        )
        form.grid_columnconfigure(
            1,
            weight=1,
        )

        self._form_label(
            form,
            0,
            "\u30db\u30b9\u30c8",
        )

        self.host_entry = self._form_entry(
            form,
            0,
            "localhost",
        )

        self._form_label(
            form,
            1,
            "\u30dd\u30fc\u30c8",
        )

        self.port_entry = self._form_entry(
            form,
            1,
            "4455",
        )

        self._form_label(
            form,
            2,
            "\u30d1\u30b9\u30ef\u30fc\u30c9",
        )

        self.password_entry = ctk.CTkEntry(
            form,
            height=38,
            corner_radius=10,
            fg_color="#F8FAFD",
            border_color="#DDE4EF",
            show="*",
        )
        self.password_entry.grid(
            row=2,
            column=1,
            sticky="ew",
            pady=6,
        )

        button_row = ctk.CTkFrame(
            card,
            fg_color="transparent",
        )
        button_row.pack(
            fill="x",
            padx=18,
            pady=(12, 16),
        )

        ctk.CTkButton(
            button_row,
            text="\u25cf  OBS\u63a5\u7d9a\u30c6\u30b9\u30c8",
            height=38,
            corner_radius=11,
            fg_color="#7C5CFC",
            hover_color="#6847E8",
            font=("Yu Gothic UI", 10, "bold"),
            command=self.test_connection,
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 6),
        )

        ctk.CTkButton(
            button_row,
            text="\u8a2d\u5b9a\u3092\u4fdd\u5b58",
            height=38,
            corner_radius=11,
            fg_color="#2F80ED",
            hover_color="#256ED0",
            font=("Yu Gothic UI", 10, "bold"),
            command=self.save_settings,
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=(6, 0),
        )


    def _form_label(
        self,
        parent,
        row,
        text,
    ):
        ctk.CTkLabel(
            parent,
            text=text,
            font=("Yu Gothic UI", 10, "bold"),
            text_color="#71809C",
        ).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=6,
        )


    def _form_entry(
        self,
        parent,
        row,
        placeholder,
    ):
        entry = ctk.CTkEntry(
            parent,
            height=38,
            corner_radius=10,
            fg_color="#F8FAFD",
            border_color="#DDE4EF",
            placeholder_text=placeholder,
        )
        entry.grid(
            row=row,
            column=1,
            sticky="ew",
            pady=6,
        )
        return entry


    def _build_quick_panel(self, parent):
        card = ctk.CTkFrame(
            parent,
            corner_radius=18,
            fg_color="#FFFFFF",
            border_width=1,
            border_color="#E7ECF4",
        )
        card.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(7, 0),
        )

        ctk.CTkLabel(
            card,
            text="\u26a1  \u30af\u30a4\u30c3\u30af\u30b3\u30f3\u30c8\u30ed\u30fc\u30eb",
            font=("Yu Gothic UI", 15, "bold"),
            text_color="#132347",
        ).pack(
            anchor="w",
            padx=18,
            pady=(16, 12),
        )

        grid = ctk.CTkFrame(
            card,
            fg_color="transparent",
        )
        grid.pack(
            fill="both",
            expand=True,
            padx=18,
            pady=(0, 16),
        )

        for column in range(2):
            grid.grid_columnconfigure(
                column,
                weight=1,
            )

        actions = [
            (
                "\u73fe\u5728\u306e\u30b7\u30fc\u30f3",
                self.get_scene,
            ),
            (
                "\u914d\u4fe1\u72b6\u614b",
                self.get_stream_status,
            ),
            (
                "\u9332\u753b\u72b6\u614b",
                self.get_record_status,
            ),
            (
                "\u30bd\u30fc\u30b9\u4e00\u89a7",
                self.get_sources,
            ),
            (
                "\u30b9\u30af\u30ea\u30fc\u30f3\u30b7\u30e7\u30c3\u30c8",
                self.save_screenshot,
            ),
            (
                "\u5168\u72b6\u614b\u3092\u66f4\u65b0",
                self.refresh_all,
            ),
        ]

        for index, (
            text,
            command,
        ) in enumerate(actions):
            button = ctk.CTkButton(
                grid,
                text=text,
                height=42,
                corner_radius=11,
                fg_color=(
                    "#F0ECFF"
                    if index == 0
                    else "#F8FAFD"
                ),
                hover_color="#EEF2FF",
                border_width=1,
                border_color="#DDE4EF",
                text_color=(
                    "#7C5CFC"
                    if index == 0
                    else "#44516A"
                ),
                font=("Yu Gothic UI", 10, "bold"),
                command=command,
            )

            button.grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=(
                    0 if index % 2 == 0 else 6,
                    6 if index % 2 == 0 else 0,
                ),
                pady=5,
            )


    def _build_bottom_area(self, parent):
        bottom = ctk.CTkFrame(
            parent,
            fg_color="transparent",
        )
        bottom.grid(
            row=2,
            column=0,
            sticky="ew",
        )

        bottom.grid_columnconfigure(
            0,
            weight=3,
        )
        bottom.grid_columnconfigure(
            1,
            weight=2,
        )

        self._build_preview_panel(bottom)
        self._build_activity_panel(bottom)


    def _build_preview_panel(self, parent):
        card = ctk.CTkFrame(
            parent,
            corner_radius=18,
            fg_color="#FFFFFF",
            border_width=1,
            border_color="#E7ECF4",
        )
        card.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 7),
        )

        header = ctk.CTkFrame(
            card,
            fg_color="transparent",
        )
        header.pack(
            fill="x",
            padx=18,
            pady=(16, 10),
        )

        ctk.CTkLabel(
            header,
            text="\u25a3  OBS\u30d7\u30ec\u30d3\u30e5\u30fc",
            font=("Yu Gothic UI", 15, "bold"),
            text_color="#132347",
        ).pack(
            side="left",
        )

        self.scene_label = ctk.CTkLabel(
            header,
            text="\u30b7\u30fc\u30f3: --",
            font=("Yu Gothic UI", 9, "bold"),
            text_color="#7C5CFC",
        )
        self.scene_label.pack(
            side="right",
        )

        preview = ctk.CTkFrame(
            card,
            height=340,
            corner_radius=14,
            fg_color="#F1F5F9",
        )
        preview.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=(0, 16),
        )
        preview.pack_propagate(False)

        self.preview_label = ctk.CTkLabel(
            preview,
            text="\u30b9\u30af\u30ea\u30fc\u30f3\u30b7\u30e7\u30c3\u30c8\u306f\u307e\u3060\u3042\u308a\u307e\u305b\u3093",
            font=("Yu Gothic UI", 11),
            text_color="#8A97AD",
        )
        self.preview_label.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=8,
        )

        self._refresh_preview()


    def _build_activity_panel(self, parent):
        card = ctk.CTkFrame(
            parent,
            corner_radius=18,
            fg_color="#FFFFFF",
            border_width=1,
            border_color="#E7ECF4",
        )
        card.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(7, 0),
        )

        ctk.CTkLabel(
            card,
            text="\u25a4  OBS\u30a2\u30af\u30c6\u30a3\u30d3\u30c6\u30a3",
            font=("Yu Gothic UI", 15, "bold"),
            text_color="#132347",
        ).pack(
            anchor="w",
            padx=18,
            pady=(16, 10),
        )

        self.status = ctk.CTkLabel(
            card,
            text="\u5f85\u6a5f\u4e2d",
            anchor="w",
            justify="left",
            wraplength=420,
            font=("Yu Gothic UI", 11, "bold"),
            text_color="#44516A",
        )
        self.status.pack(
            fill="x",
            padx=18,
            pady=(0, 10),
        )

        self.activity_box = ctk.CTkTextbox(
            card,
            height=260,
            corner_radius=12,
            fg_color="#F8FAFD",
            border_width=1,
            border_color="#E7ECF4",
            text_color="#44516A",
            font=("Yu Gothic UI", 10),
        )
        self.activity_box.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=(0, 16),
        )

        self.activity_box.insert(
            "end",
            "Livemetry Pulse OBS ready.\n",
        )


    # ==================================================
    # Settings
    # ==================================================

    def _load_settings(self):
        settings = Settings.load()

        self.host_entry.delete(
            0,
            "end",
        )
        self.host_entry.insert(
            0,
            settings.get(
                "host",
                "localhost",
            ),
        )

        self.port_entry.delete(
            0,
            "end",
        )
        self.port_entry.insert(
            0,
            settings.get(
                "port",
                "4455",
            ),
        )

        self.password_entry.delete(
            0,
            "end",
        )
        self.password_entry.insert(
            0,
            settings.get(
                "password",
                "",
            ),
        )


    def _log(self, message):
        try:
            self.activity_box.insert(
                "end",
                str(message) + "\n",
            )
            self.activity_box.see(
                "end"
            )
        except Exception:
            pass


    # ==================================================
    # OBS Actions
    # ==================================================

    def test_connection(self):
        try:
            ok = self.obs.connect(
                self.host_entry.get(),
                self.port_entry.get(),
                self.password_entry.get(),
            )

            if ok:
                self.connection_value.configure(
                    text="\u63a5\u7d9a\u4e2d",
                    text_color="#18B981",
                )

                self.header_status.configure(
                    text="\u25cf  OBS \u63a5\u7d9a\u4e2d",
                    text_color="#18B981",
                    fg_color="#EAFBF5",
                )

                self.status.configure(
                    text="OBS\u3068\u6b63\u5e38\u306b\u63a5\u7d9a\u3057\u307e\u3057\u305f\u3002"
                )

                self._log(
                    "OBS connection succeeded."
                )

                self.refresh_all()

            else:
                self._set_disconnected(
                    "OBS connection failed."
                )

        except Exception as exc:
            self._set_disconnected(
                f"OBS error: {exc}"
            )


    def save_settings(self):
        Settings.save(
            {
                "host": self.host_entry.get(),
                "port": self.port_entry.get(),
                "password": self.password_entry.get(),
            }
        )

        self.status.configure(
            text="\u8a2d\u5b9a\u3092\u4fdd\u5b58\u3057\u307e\u3057\u305f\u3002"
        )

        self._log(
            "OBS settings saved."
        )


    def get_scene(self):
        try:
            scene = self.obs.get_current_scene()

            if scene is None:
                self.status.configure(
                    text="\u30b7\u30fc\u30f3\u3092\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093\u3002"
                )
                return None

            self.scene_label.configure(
                text=f"\u30b7\u30fc\u30f3: {scene}"
            )

            self.status.configure(
                text=f"\u73fe\u5728\u306e\u30b7\u30fc\u30f3: {scene}"
            )

            self._log(
                f"Current scene: {scene}"
            )

            return scene

        except Exception as exc:
            self.status.configure(
                text=f"\u30b7\u30fc\u30f3\u53d6\u5f97\u30a8\u30e9\u30fc: {exc}"
            )
            return None


    def get_stream_status(self):
        try:
            streaming = self.obs.is_streaming()

            if streaming is None:
                self.stream_value.configure(
                    text="\u53d6\u5f97\u5931\u6557"
                )

            elif streaming:
                self.stream_value.configure(
                    text="\u914d\u4fe1\u4e2d",
                    text_color="#F04483",
                )

            else:
                self.stream_value.configure(
                    text="\u505c\u6b62\u4e2d",
                    text_color="#132347",
                )

            self._log(
                f"Streaming: {streaming}"
            )

            return streaming

        except Exception as exc:
            self._log(
                f"Stream status error: {exc}"
            )
            return None


    def get_record_status(self):
        try:
            recording = self.obs.is_recording()

            if recording is None:
                self.record_value.configure(
                    text="\u53d6\u5f97\u5931\u6557"
                )

            elif recording:
                self.record_value.configure(
                    text="\u9332\u753b\u4e2d",
                    text_color="#7C5CFC",
                )

            else:
                self.record_value.configure(
                    text="\u505c\u6b62\u4e2d",
                    text_color="#132347",
                )

            self._log(
                f"Recording: {recording}"
            )

            return recording

        except Exception as exc:
            self._log(
                f"Record status error: {exc}"
            )
            return None


    def get_sources(self):
        try:
            sources = self.obs.get_sources()

            if sources is None:
                self.status.configure(
                    text="\u30bd\u30fc\u30b9\u3092\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093\u3002"
                )
                return

            text = ", ".join(
                str(source)
                for source in sources
            )

            self.status.configure(
                text="\u30bd\u30fc\u30b9\u4e00\u89a7\u3092\u53d6\u5f97\u3057\u307e\u3057\u305f\u3002"
            )

            self._log(
                "Sources: " + text
            )

        except Exception as exc:
            self._log(
                f"Source error: {exc}"
            )


    def save_screenshot(self):
        scene = self.get_scene()

        if scene is None:
            return

        try:
            screenshot_path = (
                Path(__file__).resolve()
                .parent.parent.parent
                / "images"
                / "current.png"
            )

            screenshot_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            result = self.obs.save_screenshot(
                scene,
                str(screenshot_path),
            )

            if result:
                self.status.configure(
                    text="\u30b9\u30af\u30ea\u30fc\u30f3\u30b7\u30e7\u30c3\u30c8\u3092\u4fdd\u5b58\u3057\u307e\u3057\u305f\u3002"
                )

                self._log(
                    f"Screenshot saved: {screenshot_path}"
                )

                self._refresh_preview()

            else:
                self.status.configure(
                    text="\u30b9\u30af\u30ea\u30fc\u30f3\u30b7\u30e7\u30c3\u30c8\u4fdd\u5b58\u306b\u5931\u6557\u3057\u307e\u3057\u305f\u3002"
                )

        except Exception as exc:
            self.status.configure(
                text=f"\u30b9\u30af\u30ea\u30fc\u30f3\u30b7\u30e7\u30c3\u30c8\u30a8\u30e9\u30fc: {exc}"
            )


    def refresh_all(self):
        try:
            connected = bool(
                self.obs.is_connected()
            )
        except Exception:
            connected = False

        if connected:
            self.connection_value.configure(
                text="\u63a5\u7d9a\u4e2d",
                text_color="#18B981",
            )

            self.header_status.configure(
                text="\u25cf  OBS \u63a5\u7d9a\u4e2d",
                text_color="#18B981",
                fg_color="#EAFBF5",
            )

            self.get_scene()
            self.get_stream_status()
            self.get_record_status()

        else:
            self.connection_value.configure(
                text="\u672a\u63a5\u7d9a",
                text_color="#132347",
            )

            self.header_status.configure(
                text="\u25cf  OBS \u672a\u63a5\u7d9a",
                text_color="#71809C",
                fg_color="#F1F5F9",
            )


    def _set_disconnected(
        self,
        message,
    ):
        self.connection_value.configure(
            text="\u63a5\u7d9a\u5931\u6557",
            text_color="#E63B57",
        )

        self.header_status.configure(
            text="\u25cf  OBS \u63a5\u7d9a\u5931\u6557",
            text_color="#E63B57",
            fg_color="#FFF0F3",
        )

        self.status.configure(
            text="\u63a5\u7d9a\u306b\u5931\u6557\u3057\u307e\u3057\u305f\u3002"
        )

        self._log(message)


    # ==================================================
    # Preview
    # ==================================================

    def _refresh_preview(self):
        screenshot_path = (
            Path(__file__).resolve()
            .parent.parent.parent
            / "images"
            / "current.png"
        )

        if not screenshot_path.exists():
            return

        try:
            source = Image.open(
                screenshot_path
            )

            source.thumbnail(
                (760, 330),
                Image.Resampling.LANCZOS,
            )

            self._preview_image = ctk.CTkImage(
                light_image=source,
                dark_image=source,
                size=source.size,
            )

            self.preview_label.configure(
                text="",
                image=self._preview_image,
            )

        except Exception as exc:
            self._log(
                f"Preview error: {exc}"
            )
