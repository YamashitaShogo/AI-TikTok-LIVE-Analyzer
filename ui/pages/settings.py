import json
import os
import queue
import threading
import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog, messagebox
from core.license_client import LicenseClient
from core.secure_storage import SecureStorage

class SettingsPage(ctk.CTkFrame):
    """AI TikTok LIVE Analyzer 設定画面。"""

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
        "obs_host": "localhost",
        "obs_port": 4455,
        "obs_password": "",
        "license_key": "",
        "license_status": "未認証",
        "analysis_interval": 30,
        "screenshot_path": "images/current.png",
        "ai_prompt": (
            "あなたはTikTok LIVE分析AIです。\n\n"
            "・配信画面を100点満点で評価してください。\n"
            "・良い点を具体的に教えてください。\n"
            "・改善点を5個教えてください。\n"
            "・最後に、すぐ実行できる改善案をまとめてください。"
        ),
    }

    def __init__(self, parent, obs_client=None):
        super().__init__(parent)

        self.obs_client = obs_client

        self._destroying = False
        self._event_queue = queue.Queue()
        self._poll_job = None
        self._password_visible = False

        self._build_ui()
        self.load_settings()
        self._start_event_polling()

    # ==================================================
    # UI
    # ==================================================

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 10))

        ctk.CTkLabel(
            header,
            text="⚙ 設定",
            font=("Yu Gothic UI", 26, "bold"),
        ).pack(side="left")

        self.status_label = ctk.CTkLabel(
            header,
            text="",
            font=("Yu Gothic UI", 13),
        )
        self.status_label.pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.scroll.grid_columnconfigure(0, weight=1)

        self._build_obs_section()
        self._build_ai_section()
        self._build_license_section()
        self._build_analysis_section()
        self._build_action_section()

    def _section(self, title):
        frame = ctk.CTkFrame(self.scroll)
        frame.pack(fill="x", padx=4, pady=8)

        ctk.CTkLabel(
            frame,
            text=title,
            font=("Yu Gothic UI", 18, "bold"),
        ).pack(anchor="w", padx=16, pady=(14, 10))

        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.pack(fill="x", padx=16, pady=(0, 16))
        body.grid_columnconfigure(1, weight=1)
        return body

    @staticmethod
    def _field_label(parent, text, row):
        ctk.CTkLabel(
            parent,
            text=text,
            anchor="w",
            width=150,
            font=("Yu Gothic UI", 14),
        ).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 10),
            pady=7,
        )

    def _build_obs_section(self):
        body = self._section("📺 OBS WebSocket")

        self._field_label(body, "ホスト", 0)
        self.obs_host_entry = ctk.CTkEntry(
            body,
            placeholder_text="localhost",
        )
        self.obs_host_entry.grid(
            row=0, column=1, sticky="ew", pady=7
        )

        self._field_label(body, "ポート", 1)
        self.obs_port_entry = ctk.CTkEntry(
            body,
            placeholder_text="4455",
        )
        self.obs_port_entry.grid(
            row=1, column=1, sticky="ew", pady=7
        )

        self._field_label(body, "パスワード", 2)
        password_row = ctk.CTkFrame(body, fg_color="transparent")
        password_row.grid(
            row=2, column=1, sticky="ew", pady=7
        )
        password_row.grid_columnconfigure(0, weight=1)

        self.obs_password_entry = ctk.CTkEntry(
            password_row,
            show="●",
            placeholder_text="OBS WebSocketパスワード",
        )
        self.obs_password_entry.grid(
            row=0, column=0, sticky="ew"
        )

        ctk.CTkButton(
            password_row,
            text="表示",
            width=65,
            command=self.toggle_obs_password,
        ).grid(row=0, column=1, padx=(8, 0))

        self.obs_test_button = ctk.CTkButton(
            body,
            text="OBS接続テスト",
            width=160,
            command=self.test_obs_connection,
        )
        self.obs_test_button.grid(
            row=3,
            column=1,
            sticky="w",
            pady=(10, 0),
        )

        self.obs_test_label = ctk.CTkLabel(
            body,
            text="",
            anchor="w",
        )
        self.obs_test_label.grid(
            row=4,
            column=1,
            sticky="w",
            pady=(5, 0),
        )

    def _build_ai_section(self):
        body = self._section("🤖 OpenAI")

        self._field_label(body, "APIキー", 0)

        api_row = ctk.CTkFrame(body, fg_color="transparent")
        api_row.grid(
            row=0, column=1, sticky="ew", pady=7
        )
        api_row.grid_columnconfigure(0, weight=1)

        self.api_key_entry = ctk.CTkEntry(
            api_row,
            show="●",
            placeholder_text="sk-...",
        )
        self.api_key_entry.grid(
            row=0, column=0, sticky="ew"
        )

        self.openai_test_button = ctk.CTkButton(
            body,
            text="OpenAI接続テスト",
            width=160,
            command=self.test_openai_connection,
        )
        self.openai_test_button.grid(
            row=1,
            column=1,
            sticky="w",
            pady=(10, 0),
        )

        self.openai_test_label = ctk.CTkLabel(
            body,
            text="",
            anchor="w",
        )
        self.openai_test_label.grid(
            row=2,
            column=1,
            sticky="w",
            pady=(5, 0),
        )

        ctk.CTkLabel(
            body,
            text=(
                "APIキーはWindows Credential Managerに安全に保存されます。"
            ),
            justify="left",
            anchor="w",
            text_color=("gray35", "gray70"),
        ).grid(
            row=3,
            column=1,
            sticky="w",
            pady=(8, 0),
        )

    def _build_license_section(self):
        body = self._section("🔑 ライセンス")

        self._field_label(body, "ライセンスキー", 0)

        license_row = ctk.CTkFrame(body, fg_color="transparent")
        license_row.grid(row=0, column=1, sticky="ew", pady=7)
        license_row.grid_columnconfigure(0, weight=1)

        self.license_key_entry = ctk.CTkEntry(
            license_row,
            placeholder_text="XXXX-XXXX-XXXX-XXXX",
        )
        self.license_key_entry.grid(row=0, column=0, sticky="ew")

        self.license_test_button = ctk.CTkButton(
            license_row,
            text="認証",
            width=80,
            command=self.verify_license,
        )
        self.license_test_button.grid(row=0, column=1, padx=(8, 0))

        self.license_status_label = ctk.CTkLabel(
            body,
            text="未認証",
            anchor="w",
            text_color=("gray35", "gray70"),
        )
        self.license_status_label.grid(
            row=1,
            column=1,
            sticky="w",
            pady=(4, 0),
        )

        ctk.CTkLabel(
            body,
            text="現在は動作確認用のローカル認証です。",
            anchor="w",
            text_color=("gray35", "gray70"),
        ).grid(
            row=2,
            column=1,
            sticky="w",
            pady=(8, 0),
        )

    def _build_analysis_section(self):
        body = self._section("📊 AI分析")

        self._field_label(body, "分析間隔（秒）", 0)
        self.interval_entry = ctk.CTkEntry(
            body,
            placeholder_text="30",
        )
        self.interval_entry.grid(
            row=0, column=1, sticky="ew", pady=7
        )

        ctk.CTkLabel(
            body,
            text="10～3600秒で設定してください。",
            anchor="w",
            text_color=("gray35", "gray70"),
        ).grid(
            row=1,
            column=1,
            sticky="w",
            pady=(0, 5),
        )

        self._field_label(body, "画像保存先", 2)

        path_row = ctk.CTkFrame(body, fg_color="transparent")
        path_row.grid(
            row=2, column=1, sticky="ew", pady=7
        )
        path_row.grid_columnconfigure(0, weight=1)

        self.screenshot_path_entry = ctk.CTkEntry(
            path_row,
            placeholder_text="images/current.png",
        )
        self.screenshot_path_entry.grid(
            row=0, column=0, sticky="ew"
        )

        ctk.CTkButton(
            path_row,
            text="参照",
            width=65,
            command=self.select_screenshot_path,
        ).grid(row=0, column=1, padx=(8, 0))

        self._field_label(body, "分析プロンプト", 3)
        self.prompt_text = ctk.CTkTextbox(
            body,
            height=190,
            wrap="word",
        )
        self.prompt_text.grid(
            row=3,
            column=1,
            sticky="ew",
            pady=7,
        )

    def _build_action_section(self):
        actions = ctk.CTkFrame(self.scroll)
        actions.pack(fill="x", padx=4, pady=(12, 24))

        self.save_button = ctk.CTkButton(
            actions,
            text="💾 設定を保存",
            height=42,
            width=180,
            command=self.save_settings,
        )
        self.save_button.pack(
            side="left",
            padx=(16, 8),
            pady=16,
        )

        ctk.CTkButton(
            actions,
            text="↩ 再読み込み",
            height=42,
            width=150,
            command=self.load_settings,
        ).pack(
            side="left",
            padx=8,
            pady=16,
        )

        ctk.CTkButton(
            actions,
            text="初期値に戻す",
            height=42,
            width=150,
            fg_color="#6B7280",
            hover_color="#4B5563",
            command=self.restore_defaults,
        ).pack(
            side="left",
            padx=8,
            pady=16,
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
            self.obs_host_entry,
            settings.get("obs_host", "localhost"),
        )
        self._set_entry(
            self.obs_port_entry,
            settings.get("obs_port", 4455),
        )
        self._set_entry(
            self.obs_password_entry,
            settings.get("obs_password", ""),
        )
        try:
            api_key = SecureStorage.get_openai_api_key()
        except Exception:
            api_key = ""

        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY", "")

        self._set_entry(
            self.api_key_entry,
            api_key,
        )
        self._set_entry(
            self.license_key_entry,
            settings.get("license_key", ""),
        )
        self.license_status_label.configure(
            text=settings.get("license_status", "未認証")
        )

        self._set_entry(
            self.interval_entry,
            settings.get("analysis_interval", 30),
        )
        self._set_entry(
            self.screenshot_path_entry,
            settings.get(
                "screenshot_path",
                "images/current.png",
            ),
        )

        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert(
            "1.0",
            settings.get(
                "ai_prompt",
                self.DEFAULTS["ai_prompt"],
            ),
        )

        self.status_label.configure(
            text="設定を読み込みました"
        )

    def collect_settings(self):
        host = self.obs_host_entry.get().strip()
        port_text = self.obs_port_entry.get().strip()
        password = self.obs_password_entry.get()
        api_key = self.api_key_entry.get().strip()
        license_key = self.license_key_entry.get().strip()
        interval_text = self.interval_entry.get().strip()
        screenshot_path = self.screenshot_path_entry.get().strip()
        prompt = self.prompt_text.get("1.0", "end").strip()

        if not host:
            raise ValueError("OBSホストを入力してください。")

        try:
            port = int(port_text)
        except ValueError as exc:
            raise ValueError(
                "OBSポートは数字で入力してください。"
            ) from exc

        if not 1 <= port <= 65535:
            raise ValueError(
                "OBSポートは1～65535で設定してください。"
            )

        try:
            interval = int(interval_text)
        except ValueError as exc:
            raise ValueError(
                "分析間隔は数字で入力してください。"
            ) from exc

        if not 10 <= interval <= 3600:
            raise ValueError(
                "分析間隔は10～3600秒で設定してください。"
            )

        if not screenshot_path:
            raise ValueError(
                "スクリーンショット保存先を入力してください。"
            )

        if not prompt:
            raise ValueError(
                "AI分析プロンプトを入力してください。"
            )

        return {
            "obs_host": host,
            "obs_port": port,
            "obs_password": password,
            "openai_api_key": api_key,
            "license_key": license_key,
            "license_status": self.license_status_label.cget("text"),
            "analysis_interval": interval,
            "screenshot_path": screenshot_path,
            "ai_prompt": prompt,
        }

    def save_settings(self):
        try:
            new_settings = self.collect_settings()
            api_key = new_settings.pop(
                "openai_api_key",
                "",
            )

            # APIキーはJSONではなくWindows Credential Managerへ保存
            SecureStorage.save_openai_api_key(api_key)

            current = self._read_settings_file()

            # 過去に保存された平文APIキーも削除
            current.pop(
                "openai_api_key",
                None,
            )

            # その他の設定だけJSONへ保存
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

            # 現在のプロセスにも反映

            screenshot = Path(
                new_settings["screenshot_path"]
            )
            if screenshot.parent != Path("."):
                screenshot.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

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
            "保存ボタンを押すまではファイルに反映されません。",
        )
        if not confirmed:
            return

        defaults = dict(self.DEFAULTS)

        self._set_entry(
            self.obs_host_entry,
            defaults["obs_host"],
        )
        self._set_entry(
            self.obs_port_entry,
            defaults["obs_port"],
        )
        self._set_entry(
            self.obs_password_entry,
            defaults["obs_password"],
        )
        self._set_entry(
            self.api_key_entry,
            "",
        )
        self._set_entry(
            self.license_key_entry,
            defaults["license_key"],
        )
        self.license_status_label.configure(
            text=defaults["license_status"]
        )

        self._set_entry(
            self.interval_entry,
            defaults["analysis_interval"],
        )
        self._set_entry(
            self.screenshot_path_entry,
            defaults["screenshot_path"],
        )

        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert(
            "1.0",
            defaults["ai_prompt"],
        )

        self.status_label.configure(
            text="初期値を入力しました"
        )

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

    def test_obs_connection(self):
        try:
            host = self.obs_host_entry.get().strip()
            port = int(self.obs_port_entry.get().strip())
            password = self.obs_password_entry.get()

            if not host:
                raise ValueError(
                    "OBSホストを入力してください。"
                )
            if not 1 <= port <= 65535:
                raise ValueError(
                    "OBSポートが正しくありません。"
                )

        except ValueError as exc:
            messagebox.showwarning(
                "OBS接続テスト",
                str(exc),
            )
            return

        self.obs_test_button.configure(state="disabled")
        self.obs_test_label.configure(
            text="接続確認中..."
        )

        threading.Thread(
            target=self._obs_test_worker,
            args=(host, port, password),
            daemon=True,
        ).start()

    def _obs_test_worker(self, host, port, password):
        try:
            if self.obs_client is None:
                self._event_queue.put(
                    (
                        "obs_error",
                        "❌ OBSクライアントが初期化されていません。",
                    )
                )
                return

            connected = self.obs_client.connect(
                host,
                port,
                password,
            )

            if not connected:
                self._event_queue.put(
                    (
                        "obs_error",
                        "❌ OBSへ接続できませんでした。",
                    )
                )
                return

            client = self.obs_client.client

            if client is not None:
                version = client.get_version()
                obs_version = getattr(
                    version,
                    "obs_version",
                    "不明",
                )
            else:
                obs_version = "不明"

            self._event_queue.put(
                (
                    "obs_success",
                    f"✅ 接続成功（OBS {obs_version}）",
                )
            )

        except Exception as exc:
            self._event_queue.put(
                (
                    "obs_error",
                    f"❌ 接続失敗：{exc}",
                )
            )

    def test_openai_connection(self):
        api_key = self.api_key_entry.get().strip()

        if not api_key:
            messagebox.showwarning(
                "OpenAI接続テスト",
                "OpenAI APIキーを入力してください。",
            )
            return

        self.openai_test_button.configure(state="disabled")
        self.openai_test_label.configure(
            text="接続確認中..."
        )

        threading.Thread(
            target=self._openai_test_worker,
            args=(api_key,),
            daemon=True,
        ).start()

    def _openai_test_worker(self, api_key):
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                timeout=10.0,
            )
            client.models.list()

            self._event_queue.put(
                (
                    "openai_success",
                    "✅ OpenAI API接続成功",
                )
            )

        except Exception as exc:
            self._event_queue.put(
                (
                    "openai_error",
                    f"❌ 接続失敗：{exc}",
                )
            )

    # ==================================================
    # Events
    # ==================================================

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

            if event.startswith("obs_"):
                self.obs_test_label.configure(text=message)
                self.obs_test_button.configure(state="normal")

            elif event.startswith("openai_"):
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

    def toggle_obs_password(self):
        self._password_visible = not self._password_visible
        self.obs_password_entry.configure(
            show="" if self._password_visible else "●"
        )

    def select_screenshot_path(self):
        current = self.screenshot_path_entry.get().strip()
        initial_name = Path(
            current or "images/current.png"
        ).name

        selected = filedialog.asksaveasfilename(
            title="スクリーンショット保存先",
            defaultextension=".png",
            initialfile=initial_name,
            filetypes=[
                ("PNG画像", "*.png"),
                ("すべてのファイル", "*.*"),
            ],
        )

        if selected:
            try:
                relative = os.path.relpath(
                    selected,
                    Path.cwd(),
                )
            except ValueError:
                relative = selected

            self._set_entry(
                self.screenshot_path_entry,
                relative,
            )

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