import json
import os
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from core.license_client import LicenseClient


class LicenseWindow(ctk.CTk):
    APP_NAME = "AI-TikTok-LIVE-Analyzer"

    def __init__(self):
        super().__init__()

        self.title("Livemetry Pulse - ライセンス認証")
        self.geometry("520x280")
        self.resizable(False, False)

        self.authenticated = False
        self.license_key = None

        self._build_ui()
        self._load_saved_license_key()

    @classmethod
    def _get_settings_path(cls) -> Path:
        base = os.getenv("LOCALAPPDATA")

        if not base:
            base = os.path.join(
                os.path.expanduser("~"),
                "AppData",
                "Local",
            )

        settings_dir = Path(base) / cls.APP_NAME
        settings_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        return settings_dir / "settings.json"

    def _build_ui(self):
        ctk.CTkLabel(
            self,
            text="🔑 ライセンス認証",
            font=("Yu Gothic UI", 24, "bold"),
        ).pack(pady=(28, 12))

        ctk.CTkLabel(
            self,
            text=(
                "Livemetry Pulse を使用するには\n"
                "ライセンスキーを入力してください。"
            ),
            font=("Yu Gothic UI", 14),
            justify="center",
        ).pack(pady=(0, 18))

        self.license_entry = ctk.CTkEntry(
            self,
            width=380,
            height=40,
            placeholder_text="ATLA-XXXX-XXXX-XXXX",
        )
        self.license_entry.pack(pady=(0, 12))

        self.status_label = ctk.CTkLabel(
            self,
            text="",
            font=("Yu Gothic UI", 13),
        )
        self.status_label.pack(pady=(0, 10))

        self.verify_button = ctk.CTkButton(
            self,
            text="ライセンス認証",
            width=180,
            height=40,
            command=self.verify_license,
        )
        self.verify_button.pack()

    def _load_saved_license_key(self):
        """保存済みライセンスキーがあれば入力欄へ表示する。"""
        path = self._get_settings_path()

        if not path.exists():
            return

        try:
            with path.open(
                "r",
                encoding="utf-8",
            ) as file:
                settings = json.load(file)

            if not isinstance(settings, dict):
                return

            key = str(
                settings.get(
                    "license_key",
                    "",
                )
            ).strip()

            if key:
                self.license_entry.insert(
                    0,
                    key,
                )

        except (OSError, json.JSONDecodeError):
            pass

    def _save_license(self, key, status):
        """認証結果をsettings.jsonへ保存する。"""
        path = self._get_settings_path()

        settings = {}

        if path.exists():
            try:
                with path.open(
                    "r",
                    encoding="utf-8",
                ) as file:
                    loaded = json.load(file)

                if isinstance(loaded, dict):
                    settings = loaded

            except (OSError, json.JSONDecodeError):
                settings = {}

        settings["license_key"] = key
        settings["license_status"] = status

        temp_path = path.with_suffix(
            ".json.tmp"
        )

        with temp_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                settings,
                file,
                ensure_ascii=False,
                indent=4,
            )

        temp_path.replace(path)

    def verify_license(self):
        key = "".join(
            self.license_entry.get().split()
        ).upper()

        if not key:
            messagebox.showwarning(
                "ライセンス認証",
                "ライセンスキーを入力してください。",
            )
            return

        self.verify_button.configure(
            state="disabled"
        )
        self.status_label.configure(
            text="認証中..."
        )
        self.update_idletasks()

        result = LicenseClient.verify(key)

        self.verify_button.configure(
            state="normal"
        )

        if result.get("valid"):
            self.authenticated = True
            self.license_key = key

            plan = result.get(
                "plan",
                "standard",
            )
            expires_at = result.get(
                "expires_at",
                "未設定",
            )

            try:
                self._save_license(
                    key,
                    "✅ 認証済み",
                )
            except OSError as exc:
                messagebox.showerror(
                    "保存エラー",
                    "ライセンス情報を保存できませんでした。\n\n"
                    f"{exc}",
                )
                self.authenticated = False
                return

            messagebox.showinfo(
                "ライセンス認証",
                "ライセンス認証に成功しました。\n\n"
                f"プラン: {plan}\n"
                f"有効期限: {expires_at}",
            )

            self.destroy()

        else:
            status = result.get(
                "status",
                "invalid",
            )

            message = result.get(
                "message",
                "ライセンス認証に失敗しました。",
            )

            self.status_label.configure(
                text=f"❌ 認証失敗: {status}"
            )

            try:
                self._save_license(
                    key,
                    "❌ 未認証",
                )
            except OSError:
                pass

            messagebox.showerror(
                "ライセンス認証",
                message,
            )