import os
import sys
import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from core.license_manager import LicenseManager
from core.obs_client import OBSClient
from ui.pages.ai import AIPage
from ui.pages.analytics import AnalyticsPage
from ui.pages.dashboard import DashboardPage
from ui.pages.history import HistoryPage
from ui.pages.obs import OBSPage
from ui.pages.settings import SettingsPage


def resource_path(relative_path: str) -> str:
    """
    通常起動とPyInstallerでEXE化した場合の両方に対応した
    ファイルパスを返します。
    """
    if hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent.parent

    return str(base_path / relative_path)


class MainWindow(ctk.CTk):
    """AI TikTok LIVE Analyzer メインウィンドウ。"""


    def __init__(self):
        super().__init__()

        # ライセンスオンライン確認用
        self._license_check_running = False
        self._license_online_valid = None
        self._closing = False

        self.title("AI TikTok LIVE Analyzer")
        self.geometry("1200x900")
        self.minsize(1000, 700)

        self.after(200, self.set_app_icon)

        self.obs = OBSClient()
        self.current_page = None

        self._closing = False

        title = ctk.CTkLabel(
            self,
            text="AI TikTok LIVE Analyzer",
            font=("Yu Gothic UI", 28, "bold"),
        )
        title.pack(pady=(20, 0))

        container = ctk.CTkFrame(self)
        container.pack(
            fill="both",
            expand=True,
            padx=20,
            pady=20,
        )

        menu = ctk.CTkFrame(
            container,
            width=180,
        )
        menu.pack(
            side="left",
            fill="y",
            padx=(0, 15),
        )
        menu.pack_propagate(False)

        ctk.CTkLabel(
            menu,
            text="MENU",
            font=("Yu Gothic UI", 20, "bold"),
        ).pack(pady=(20, 20))

        self.license_label = ctk.CTkLabel(
            menu,
            text="🔄 ライセンス確認中",
            font=("Yu Gothic UI", 12, "bold"),
        )
        self.license_label.pack(pady=(0, 18))

        self.dashboard_button = ctk.CTkButton(
            menu,
            text="🏠 Dashboard",
            width=160,
            command=self.show_dashboard,
        )
        self.dashboard_button.pack(pady=5)

        self.obs_button = ctk.CTkButton(
            menu,
            text="📡 OBS",
            width=160,
            command=self.show_obs,
        )
        self.obs_button.pack(pady=5)

        self.ai_button = ctk.CTkButton(
            menu,
            text="🤖 AI",
            width=160,
            command=self.show_ai,
        )
        self.ai_button.pack(pady=5)

        self.history_button = ctk.CTkButton(
            menu,
            text="📋 履歴",
            width=160,
            command=self.show_history,
        )
        self.history_button.pack(pady=5)

        self.analytics_button = ctk.CTkButton(
            menu,
            text="📈 Analytics",
            width=160,
            command=self.show_analytics,
        )
        self.analytics_button.pack(pady=5)

        self.settings_button = ctk.CTkButton(
            menu,
            text="⚙ Settings",
            width=160,
            command=self.show_settings,
        )
        self.settings_button.pack(pady=5)

        self.content = ctk.CTkFrame(container)
        self.content.pack(
            side="left",
            fill="both",
            expand=True,
        )

        self.show_dashboard()

        # app.py 側で起動前ライセンス認証済みなので、
        # メイン画面表示時にライセンス表示を更新
        self.refresh_license_status()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ==================================================
    # App icon
    # ==================================================

    def set_app_icon(self):
        """アプリのタイトルバーアイコンを設定します。"""
        icon_path = resource_path(
            os.path.join(
                "assets",
                "AI_TikTok_LIVE_Analyzer.ico",
            )
        )

        if not os.path.exists(icon_path):
            print(f"アイコンが見つかりません: {icon_path}")
            return

        try:
            self.iconbitmap(icon_path)
        except Exception as error:
            print(f"アイコン設定エラー: {error}")

    # ==================================================
    # License
    # ==================================================

    def refresh_license_status(self):
        """左メニューのライセンス表示を更新します。"""
        if LicenseManager.is_licensed():
            self.license_label.configure(
                text="🔑 ライセンス認証済み",
            )
        else:
            self.license_label.configure(
                text="🔒 ライセンス未認証",
            )

    def start_online_license_check(self):
        """
        アプリ起動時などに保存済みライセンスを
        バックグラウンドでオンライン確認します。
        """
        if self._closing:
            return

        if self._license_check_running:
            return

        data = LicenseManager.get_license_data()
        license_key = str(
            data.get("license_key", "")
        ).strip()

        if not license_key:
            self._license_online_valid = False
            self.refresh_license_status()
            return

        self._license_check_running = True
        self.license_label.configure(
            text="🔄 ライセンス確認中",
        )

        threading.Thread(
            target=self._license_check_worker,
            daemon=True,
            name="LicenseCheckThread",
        ).start()

    def _license_check_worker(self):
        try:
            result = LicenseManager.verify_online()
        except Exception as exc:
            result = {
                "valid": False,
                "status": "error",
                "message": f"ライセンス確認エラー: {exc}",
            }

        if self._closing:
            return

        self.after(
            0,
            lambda: self._apply_online_license_result(result),
        )

    def _apply_online_license_result(self, result: dict):
        self._license_check_running = False

        if self._closing:
            return

        valid = bool(result.get("valid"))
        status = str(result.get("status", "")).strip()
        message = str(result.get("message", "")).strip()

        self._license_online_valid = valid
        self.refresh_license_status()

        if valid:
            self.license_label.configure(
                text="🔑 ライセンス認証済み"
            )
            return

        if status == "missing":
            self.license_label.configure(
                text="🔒 ライセンス未認証"
            )
            return

        if status == "offline":
            self.license_label.configure(
                text="⚠ ライセンス確認不可"
            )
            return

        self.license_label.configure(
            text="🔒 ライセンス無効"
        )

        # 停止・期限切れなどは利用不可として扱う
        if status in {
            "inactive",
            "expired",
            "invalid",
            "server_error",
            "error",
        }:
            if self.current_page is not None and not isinstance(
                self.current_page,
                SettingsPage,
            ):
                self.show_settings()

            if message:
                messagebox.showwarning(
                    "ライセンス確認",
                    message,
                )

    def require_license(self) -> bool:
        """
        有料機能を開く前にローカル状態と、
        起動時オンライン確認結果の両方を確認します。
        """
        self.refresh_license_status()

        if not LicenseManager.is_licensed():
            messagebox.showwarning(
                "ライセンス認証が必要です",
                "この機能を使用するにはライセンス認証が必要です。\n\n"
                "Settings画面でライセンスキーを入力し、"
                "オンライン認証してください。",
            )
            return False

        # 起動時オンライン確認で明確に無効と判定された場合
        if self._license_online_valid is False:
            messagebox.showwarning(
                "ライセンスが無効です",
                "保存済みライセンスをオンラインで確認できませんでした。\n\n"
                "Settings画面でライセンス状態を確認してください。",
            )
            return False

        return True

    # ==================================================
    # Pages
    # ==================================================

    def clear_page(self):
        """現在表示しているページを削除します。"""
        if self.current_page is not None:
            self.current_page.destroy()
            self.current_page = None

    def show_dashboard(self):
        self.clear_page()
        self.current_page = DashboardPage(
            self.content,
            self.obs,
        )
        self.current_page.pack(
            fill="both",
            expand=True,
        )

    def show_obs(self):
        self.clear_page()
        self.current_page = OBSPage(
            self.content,
            self.obs,
        )
        self.current_page.pack(
            fill="both",
            expand=True,
        )

    def show_ai(self):
        if not self.require_license():
            return

        self.clear_page()
        self.current_page = AIPage(
            self.content,
            self.obs,
        )
        self.current_page.pack(
            fill="both",
            expand=True,
        )

    def show_history(self):
        if not self.require_license():
            return

        self.clear_page()
        self.current_page = HistoryPage(
            self.content,
        )
        self.current_page.pack(
            fill="both",
            expand=True,
        )

    def show_analytics(self):
        if not self.require_license():
            return

        self.clear_page()
        self.current_page = AnalyticsPage(
            self.content,
        )
        self.current_page.pack(
            fill="both",
            expand=True,
        )

    def show_settings(self):
        self.clear_page()
        self.current_page = SettingsPage(
        self.content,
        self.obs,
    )
        self.current_page.pack(
            fill="both",
            expand=True,
        )

        # Settingsで認証後に左メニューを更新
        self.after(
            500,
            self._refresh_after_settings,
        )

    def _refresh_after_settings(self):
        if self._closing:
            return

        self.refresh_license_status()

        # 認証済みキーが保存されていればオンライン再確認
        data = LicenseManager.get_license_data()

        if data.get("license_key"):
            self.start_online_license_check()

    # ==================================================
    # Close
    # ==================================================

    def on_close(self):
        """アプリ終了時の処理です。"""
        self._closing = True

        try:
            if self.current_page is not None:
                self.current_page.destroy()
                self.current_page = None
        except Exception:
            pass

        try:
            if hasattr(self.obs, "disconnect"):
                self.obs.disconnect()
        except Exception as error:
            print(f"OBS切断時のエラー: {error}")

        self.destroy()