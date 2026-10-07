import base64
import json
import os
import queue
import threading
import customtkinter as ctk
from io import BytesIO
from pathlib import Path
from tkinter import messagebox
from urllib import error, request

from PIL import Image

from core.ai_client import AIClient
from core.license_client import LicenseClient
from core.settings import Settings as AppSettings

class SettingsPage(ctk.CTkFrame):
    """Livemetry Pulse 設定画面。"""

    APP_NAME = "AI-TikTok-LIVE-Analyzer"

    @classmethod
    def _get_settings_path(cls):
        base = os.getenv("LOCALAPPDATA")
        if not base:
            base = os.path.join(os.path.expanduser("~"), "AppData", "Local")
        settings_dir = Path(base) / cls.APP_NAME
        settings_dir.mkdir(parents=True, exist_ok=True)
        return settings_dir / "settings.json"


    DEFAULTS = {
        "license_key": "",
        "license_status": "未認証",
        "appearance_mode": "dark",
        "analysis_interval": 30,
        "ai_prompt": (
            "あなたはTikTok LIVE分析AIです。\n\n"
            "・配信画面を100点満点で評価してください。\n"
            "・良い点を具体的に教えてください。\n"
            "・改善点を5個教えてください。\n"
            "・最後に、すぐ実行できる改善案をまとめてください。"
        ),
    }

    def __init__(self, parent):
        super().__init__(parent)

        self._destroying = False
        self._event_queue = queue.Queue()
        self._poll_job = None
        self._build_ui()
        self.load_settings()
        self._start_event_polling()

    # ==================================================
    # UI
    # ==================================================


    def _build_ui(self):
        self.configure(fg_color=("#F6F8FC", "#0B1120"))

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(24, 12))

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left")

        ctk.CTkLabel(
            title_box,
            text="設定",
            font=("Yu Gothic UI", 28, "bold"),
            text_color=("#111827", "#F8FAFC"),
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_box,
            text="Livemetry Pulse の動作や分析設定を管理します。",
            font=("Yu Gothic UI", 12),
            text_color=("#64748B", "#94A3B8"),
        ).pack(anchor="w", pady=(2, 0))

        self.status_label = ctk.CTkLabel(
            header,
            text="",
            font=("Yu Gothic UI", 12, "bold"),
            text_color=("#4565D8", "#AFC0FF"),
        )
        self.status_label.pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=24, pady=(0, 24))

        self._build_quick_setup_section()
        self._build_ai_section()
        self._build_license_section()
        self._build_analysis_section()
        self._build_appearance_section()
        self._build_action_section()

    def _build_quick_setup_section(self):
        frame = ctk.CTkFrame(
            self.scroll,
            corner_radius=18,
            fg_color=("#EEF2FF", "#17213A"),
            border_width=1,
            border_color=("#DDE5FF", "#2C3B63"),
        )
        frame.pack(fill="x", padx=4, pady=(8, 14))

        ctk.CTkLabel(
            frame,
            text="初回セットアップ",
            font=("Yu Gothic UI", 18, "bold"),
            text_color=("#3049A8", "#C7D2FE"),
        ).pack(anchor="w", padx=18, pady=(16, 6))

        guide_text = (
            "初めて利用する場合は、次の順番で確認してください。\n\n"
            "① TikTok ViewerでLIVE映像が「取得中」になることを確認\n"
            "② ライセンスキーを入力して認証\n"
            "③ 「AIサーバー接続テスト」で接続を確認\n"
            "④ AI分析間隔などを設定\n"
            "⑤ 「設定を保存」を押す\n"
            "⑥ DashboardからAI分析を開始"
        )

        ctk.CTkLabel(
            frame,
            text=guide_text,
            justify="left",
            anchor="w",
            font=("Yu Gothic UI", 13),
            text_color=("#475569", "#CBD5E1"),
        ).pack(fill="x", padx=18, pady=(0, 16))

    def _section(self, title):
        frame = ctk.CTkFrame(
            self.scroll,
            corner_radius=18,
            fg_color=("#FFFFFF", "#111827"),
            border_width=1,
            border_color=("#E6EAF2", "#243047"),
        )
        frame.pack(fill="x", padx=4, pady=8)

        ctk.CTkLabel(
            frame,
            text=title,
            font=("Yu Gothic UI", 18, "bold"),
            text_color=("#172033", "#F8FAFC"),
        ).pack(anchor="w", padx=18, pady=(16, 10))

        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=(0, 18))
        body.grid_columnconfigure(1, weight=1)
        return body

    @staticmethod
    def _field_label(parent, text, row):
        ctk.CTkLabel(
            parent,
            text=text,
            anchor="w",
            width=150,
            font=("Yu Gothic UI", 13, "bold"),
            text_color=("#475569", "#CBD5E1"),
        ).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=8,
        )

    def _build_ai_section(self):
        body = self._section("AIサーバー")

        ctk.CTkLabel(
            body,
            text=(
                "AI分析はサーバー経由で実行されます。\n"
                "このPCにOpenAI APIキーを設定する必要はありません。"
            ),
            justify="left",
            anchor="w",
            font=("Yu Gothic UI", 13),
            text_color=("#64748B", "#94A3B8"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self.openai_test_button = ctk.CTkButton(
            body,
            text="AIサーバー接続テスト",
            width=190,
            height=38,
            corner_radius=10,
            fg_color=("#4565D8", "#526EE8"),
            hover_color=("#3855C2", "#617BF0"),
            command=self.test_ai_server_connection,
        )
        self.openai_test_button.grid(row=1, column=1, sticky="w", pady=(8, 0))

        self.openai_test_label = ctk.CTkLabel(
            body,
            text="",
            anchor="w",
            font=("Yu Gothic UI", 12),
            text_color=("#64748B", "#94A3B8"),
        )
        self.openai_test_label.grid(row=2, column=1, sticky="w", pady=(6, 0))

    def _build_license_section(self):
        body = self._section("ライセンス")
        self._field_label(body, "ライセンスキー", 0)

        license_row = ctk.CTkFrame(body, fg_color="transparent")
        license_row.grid(row=0, column=1, sticky="ew", pady=7)
        license_row.grid_columnconfigure(0, weight=1)

        self.license_key_entry = ctk.CTkEntry(
            license_row,
            placeholder_text="XXXX-XXXX-XXXX-XXXX",
            height=40,
            corner_radius=10,
            fg_color=("#F8FAFC", "#0F172A"),
            border_color=("#D9E0EA", "#334155"),
        )
        self.license_key_entry.grid(row=0, column=0, sticky="ew")

        self.license_test_button = ctk.CTkButton(
            license_row,
            text="認証",
            width=84,
            height=40,
            corner_radius=10,
            fg_color=("#4565D8", "#526EE8"),
            hover_color=("#3855C2", "#617BF0"),
            command=self.verify_license,
        )
        self.license_test_button.grid(row=0, column=1, padx=(8, 0))

        self.license_status_label = ctk.CTkLabel(
            body,
            text="未認証",
            anchor="w",
            font=("Yu Gothic UI", 12, "bold"),
            text_color=("#64748B", "#94A3B8"),
        )
        self.license_status_label.grid(row=1, column=1, sticky="w", pady=(4, 0))

        ctk.CTkLabel(
            body,
            text="ライセンスはオンラインで認証されます。",
            anchor="w",
            font=("Yu Gothic UI", 11),
            text_color=("#94A3B8", "#64748B"),
        ).grid(row=2, column=1, sticky="w", pady=(8, 0))

    def _build_analysis_section(self):
        body = self._section("AI分析")

        self._field_label(body, "分析間隔（秒）", 0)
        self.interval_entry = ctk.CTkEntry(
            body,
            placeholder_text="30",
            height=40,
            corner_radius=10,
            fg_color=("#F8FAFC", "#0F172A"),
            border_color=("#D9E0EA", "#334155"),
        )
        self.interval_entry.grid(row=0, column=1, sticky="ew", pady=7)

        ctk.CTkLabel(
            body,
            text="10～3600秒で設定してください。",
            anchor="w",
            font=("Yu Gothic UI", 11),
            text_color=("#94A3B8", "#64748B"),
        ).grid(row=1, column=1, sticky="w", pady=(0, 5))

        self._field_label(body, "分析プロンプト", 2)
        self.prompt_text = ctk.CTkTextbox(
            body,
            height=190,
            wrap="word",
            corner_radius=12,
            fg_color=("#F8FAFC", "#0F172A"),
            border_width=1,
            border_color=("#D9E0EA", "#334155"),
            text_color=("#334155", "#E2E8F0"),
        )
        self.prompt_text.grid(row=2, column=1, sticky="ew", pady=7)

    def _build_appearance_section(self):
        body = self._section("外観")

        self._field_label(
            body,
            "テーマ",
            0,
        )

        self.appearance_mode_var = ctk.StringVar(
            value="ダーク"
        )

        theme_box = ctk.CTkFrame(
            body,
            fg_color="transparent",
        )
        theme_box.grid(
            row=0,
            column=1,
            sticky="w",
            pady=(6, 4),
        )

        self.appearance_mode_control = ctk.CTkSegmentedButton(
            theme_box,
            values=[
                "ライト",
                "ダーク",
            ],
            variable=self.appearance_mode_var,
            command=self._on_appearance_change,
            width=240,
            height=40,
            corner_radius=10,
            border_width=1,
            fg_color=("#F1F5F9", "#1E293B"),
            selected_color=("#4F6FEA", "#526EE8"),
            selected_hover_color=("#3F5DD5", "#617BF0"),
            unselected_color=("#F8FAFC", "#111827"),
            unselected_hover_color=("#E8EEF8", "#273449"),
            text_color=("#475569", "#CBD5E1"),
            text_color_disabled=("#94A3B8", "#64748B"),
            font=("Yu Gothic UI", 13, "bold"),
            dynamic_resizing=False,
        )
        self.appearance_mode_control.pack()

        ctk.CTkLabel(
            body,
            text="アプリ全体の表示テーマを切り替えます。変更はすぐに反映されます。",
            anchor="w",
            font=("Yu Gothic UI", 11),
            text_color=("#94A3B8", "#64748B"),
        ).grid(
            row=1,
            column=1,
            sticky="w",
            pady=(4, 8),
        )
    def _build_action_section(self):
        actions = ctk.CTkFrame(
            self.scroll,
            corner_radius=18,
            fg_color=("#FFFFFF", "#111827"),
            border_width=1,
            border_color=("#E6EAF2", "#243047"),
        )
        actions.pack(fill="x", padx=4, pady=(12, 24))

        self.save_button = ctk.CTkButton(
            actions,
            text="設定を保存",
            height=42,
            width=180,
            corner_radius=10,
            fg_color=("#4565D8", "#526EE8"),
            hover_color=("#3855C2", "#617BF0"),
            command=self.save_settings,
        )
        self.save_button.pack(side="left", padx=(16, 8), pady=16)

        ctk.CTkButton(
            actions,
            text="再読み込み",
            height=42,
            width=150,
            corner_radius=10,
            fg_color=("#FFFFFF", "#111827"),
            hover_color=("#EEF2FF", "#1E293B"),
            text_color=("#3157D5", "#AFC0FF"),
            border_width=1,
            border_color=("#D9E0F0", "#334155"),
            command=self.load_settings,
        ).pack(side="left", padx=8, pady=16)

        ctk.CTkButton(
            actions,
            text="初期値に戻す",
            height=42,
            width=150,
            corner_radius=10,
            fg_color=("#F3F4F6", "#1F2937"),
            hover_color=("#E5E7EB", "#374151"),
            text_color=("#4B5563", "#D1D5DB"),
            command=self.restore_defaults,
        ).pack(side="left", padx=8, pady=16)

    @staticmethod
    def _appearance_label_to_mode(value):
        return {
            "\u30e9\u30a4\u30c8": "light",
            "\u30c0\u30fc\u30af": "dark",
        }.get(str(value), "dark")

    @staticmethod
    def _appearance_mode_to_label(value):
        return {
            "light": "\u30e9\u30a4\u30c8",
            "dark": "\u30c0\u30fc\u30af",
        }.get(str(value).lower(), "\u30c0\u30fc\u30af")

    def _on_appearance_change(self, value):
        mode = self._appearance_label_to_mode(value)

        ctk.set_appearance_mode(mode)

        try:
            settings = AppSettings.load()
            settings["appearance_mode"] = mode
            AppSettings.save(settings)

            self.status_label.configure(
                text="\u5916\u89b3\u3092\u5909\u66f4\u3057\u307e\u3057\u305f"
            )

        except Exception as exc:
            messagebox.showerror(
                "\u5916\u89b3\u8a2d\u5b9a",
                (
                    "\u30c6\u30fc\u30de\u8a2d\u5b9a\u3092"
                    "\u4fdd\u5b58\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002\n\n"
                    f"{exc}"
                ),
            )


    # ==================================================
    # Settings
    # ==================================================

    def _read_settings_file(self):
        settings = dict(self.DEFAULTS)

        if not self._get_settings_path().exists():
            return settings

        try:
            with self._get_settings_path().open(
                "r",
                encoding="utf-8",
            ) as file:
                loaded = json.load(file)

            if isinstance(loaded, dict):
                settings.update(loaded)

                for suffix in ("host", "port", "password"):
                    settings.pop("obs_" + suffix, None)

        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showwarning(
                "設定読込",
                "settings.jsonを読み込めなかったため、"
                f"初期値を使用します。\n\n{exc}",
            )

        return settings


    def load_settings(self):
        settings = self._read_settings_file()

        self._set_entry(
            self.license_key_entry,
            settings.get("license_key", ""),
        )
        self.license_status_label.configure(
            text=settings.get("license_status", "未認証")
        )

        if hasattr(self, "appearance_mode_var"):
            appearance_mode = str(
                settings.get("appearance_mode", "dark")
            ).strip().lower()
            self.appearance_mode_var.set(
                self._appearance_mode_to_label(appearance_mode)
            )

        self._set_entry(
            self.interval_entry,
            settings.get("analysis_interval", 30),
        )

        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert(
            "1.0",
            settings.get("ai_prompt", self.DEFAULTS["ai_prompt"]),
        )

        self.status_label.configure(text="設定を読み込みました")

    
    
    def collect_settings(self):
        license_key = self.license_key_entry.get().strip()
        interval_text = self.interval_entry.get().strip()
        prompt = self.prompt_text.get("1.0", "end").strip()

        try:
            interval = int(interval_text)
        except ValueError as exc:
            raise ValueError("AI分析間隔は数字で入力してください。") from exc

        if not 10 <= interval <= 3600:
            raise ValueError("AI分析間隔は10〜3600秒で設定してください。")
        if not prompt:
            raise ValueError("AI分析プロンプトを入力してください。")

        appearance_mode = "dark"
        if hasattr(self, "appearance_mode_var"):
            appearance_mode = self._appearance_label_to_mode(
                self.appearance_mode_var.get()
            )

        return {
            "license_key": license_key,
            "license_status": self.license_status_label.cget("text"),
            "appearance_mode": appearance_mode,
            "analysis_interval": interval,
            "ai_prompt": prompt,
        }

    
    
    def save_settings(self):
        try:
            new_settings = self.collect_settings()
            current = self._read_settings_file()
    
            # 旧バージョンでsettings.jsonに保存されていた
            # OpenAI APIキーがあれば削除します。
            current.pop(
                "openai_api_key",
                None,
            )
    
            current.update(new_settings)
    
            self._get_settings_path().parent.mkdir(
                parents=True,
                exist_ok=True,
            )
    
            temp_path = self._get_settings_path().with_suffix(".json.tmp")
    
            with temp_path.open(
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    current,
                    file,
                    ensure_ascii=False,
                    indent=4,
                )
    
            temp_path.replace(self._get_settings_path())
    
    
            self.status_label.configure(
                text="✅ 保存しました"
            )
    
            messagebox.showinfo(
                "設定保存",
                "設定を保存しました。\n\n"
                "自動分析が動作中の場合は、"
                "いったん停止してから再開してください。",
            )
    
        except ValueError as exc:
            messagebox.showwarning(
                "入力エラー",
                str(exc),
            )
        except OSError as exc:
            messagebox.showerror(
                "保存エラー",
                f"設定を保存できませんでした。\n\n{exc}",
            )
    
    
    def restore_defaults(self):
        confirmed = messagebox.askyesno(
            "初期値に戻す",
            "入力内容を初期値に戻しますか？\n"
            "「設定を保存」を押すまではファイルには反映されません。",
        )
        if not confirmed:
            return

        defaults = dict(self.DEFAULTS)

        self._set_entry(
            self.license_key_entry,
            defaults["license_key"],
        )
        self.license_status_label.configure(
            text=defaults["license_status"]
        )

        if hasattr(self, "appearance_mode_var"):
            self.appearance_mode_var.set(
                self._appearance_mode_to_label(
                    defaults.get("appearance_mode", "dark")
                )
            )

        self._set_entry(
            self.interval_entry,
            defaults["analysis_interval"],
        )

        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", defaults["ai_prompt"])
        self.status_label.configure(text="初期値を入力しました")

    
    def verify_license(self):
        """オンラインライセンス認証。"""
        raw_key = self.license_key_entry.get()
        key = "".join(raw_key.split()).upper()

        if not key:
            messagebox.showwarning(
                "ライセンス認証",
                "ライセンスキーを入力してください。",
            )
            return

        self.license_test_button.configure(state="disabled")
        self.license_status_label.configure(
            text="認証中..."
        )
        self.status_label.configure(
            text="ライセンスサーバーへ確認中..."
        )

        threading.Thread(
            target=self._license_verify_worker,
            args=(key,),
            daemon=True,
        ).start()

    def _license_verify_worker(self, key):
        result = LicenseClient.verify(key)

        self._event_queue.put(
            (
                "license_result",
                {
                    "key": key,
                    "result": result,
                },
            )
        )

    def _apply_license_result(self, payload):
        key = payload["key"]
        result = payload["result"]

        valid = bool(result.get("valid"))
        message = str(
            result.get(
                "message",
                "ライセンス認証結果を取得できませんでした。",
            )
        )

        if valid:
            status = "✅ 認証済み"
            self._set_entry(
                self.license_key_entry,
                key,
            )
            self.license_status_label.configure(
                text=status
            )
            self.status_label.configure(
                text="✅ ライセンスを認証しました"
            )

            if not self._save_license_result(
                key,
                status,
            ):
                return

            plan = result.get("plan")
            expires_at = result.get("expires_at")

            details = message
            if plan:
                details += f"\nプラン: {plan}"
            if expires_at:
                details += f"\n有効期限: {expires_at}"

            messagebox.showinfo(
                "ライセンス認証",
                details,
            )

        else:
            status_name = str(
                result.get(
                    "status",
                    "invalid",
                )
            )

            status = "❌ 未認証"
            self.license_status_label.configure(
                text=status
            )
            self.status_label.configure(
                text=f"ライセンス認証失敗: {status_name}"
            )

            self._save_license_result(
                key,
                status,
            )

            messagebox.showerror(
                "ライセンス認証",
                message,
            )

    def _save_license_result(self, key, status):
        """ライセンス認証結果をsettings.jsonへ保存します。"""
        try:
            current = self._read_settings_file()
            current["license_key"] = key
            current["license_status"] = status

            self._get_settings_path().parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            temp_path = self._get_settings_path().with_suffix(
                ".json.tmp"
            )

            with temp_path.open(
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    current,
                    file,
                    ensure_ascii=False,
                    indent=4,
                )

            temp_path.replace(self._get_settings_path())

            # MainWindowの左メニューもすぐ更新します。
            root = self.winfo_toplevel()
            refresh = getattr(
                root,
                "refresh_license_status",
                None,
            )
            if callable(refresh):
                refresh()

            return True

        except OSError as exc:
            self.license_status_label.configure(
                text="❌ 保存失敗"
            )
            messagebox.showerror(
                "ライセンス保存エラー",
                "settings.jsonへ保存できませんでした。\n\n"
                f"{exc}",
            )
            return False

    # ==================================================
    # Connection tests
    # ==================================================




    def test_ai_server_connection(self):
        raw_key = self.license_key_entry.get()
        key = "".join(raw_key.split()).upper()
    
        if not key:
            messagebox.showwarning(
                "AIサーバー接続テスト",
                "先にライセンスキーを入力してください。",
            )
            return
    
        self.openai_test_button.configure(state="disabled")
        self.openai_test_label.configure(
            text="接続確認中..."
        )
    
        threading.Thread(
            target=self._ai_server_test_worker,
            args=(key,),
            daemon=True,
        ).start()
    
    
    def _ai_server_test_worker(self, license_key):
        try:
            # 小さなテスト画像を生成し、実際のAI分析経路を確認します。
            image = Image.new(
                "RGB",
                (64, 64),
                "white",
            )
            buffer = BytesIO()
            image.save(
                buffer,
                format="JPEG",
                quality=80,
            )
    
            payload = json.dumps(
                {
                    "license_key": license_key,
                    "prompt": "接続テストです。『接続成功』とだけ返してください。",
                    "image_base64": base64.b64encode(
                        buffer.getvalue()
                    ).decode("utf-8"),
                }
            ).encode("utf-8")
    
            req = request.Request(
                AIClient.SERVER_ANALYZE_URL,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
    
            with request.urlopen(
                req,
                timeout=AIClient.SERVER_TIMEOUT,
            ) as response:
                result = json.loads(
                    response.read().decode("utf-8")
                )
    
            if not isinstance(result, dict) or not result.get("success"):
                raise RuntimeError(
                    "AIサーバーから正常な応答を取得できませんでした。"
                )
    
            self._event_queue.put(
                (
                    "ai_server_success",
                    "✅ AIサーバー接続成功",
                )
            )
    
        except error.HTTPError as exc:
            try:
                response_data = json.loads(
                    exc.read().decode("utf-8")
                )
                message = response_data.get(
                    "detail",
                    f"HTTPエラー: {exc.code}",
                )
            except Exception:
                message = f"HTTPエラー: {exc.code}"
    
            self._event_queue.put(
                (
                    "ai_server_error",
                    f"❌ 接続失敗：{message}",
                )
            )
    
        except Exception as exc:
            self._event_queue.put(
                (
                    "ai_server_error",
                    f"❌ 接続失敗：{exc}",
                )
            )
    
    def _start_event_polling(self):
        if self._destroying:
            return

        self._process_events()
        self._poll_job = self.after(
            100,
            self._start_event_polling,
        )

    def _process_events(self):
        while True:
            try:
                event, message = self._event_queue.get_nowait()
            except queue.Empty:
                break

            if event.startswith("ai_server_"):
                self.openai_test_label.configure(text=message)
                self.openai_test_button.configure(state="normal")

            elif event == "license_result":
                self.license_test_button.configure(state="normal")
                self._apply_license_result(message)


    # ==================================================
    # Helpers
    # ==================================================

    @staticmethod
    def _set_entry(entry, value):
        entry.delete(0, "end")
        entry.insert(0, str(value))


    def destroy(self):
        if self._destroying:
            return

        self._destroying = True

        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None

        super().destroy()
