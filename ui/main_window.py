import os
import sys
import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from core.license_manager import LicenseManager
from core.obs_client import OBSClient
from core.settings import Settings
from ui.pages.ai import AIPage
from ui.pages.analytics import AnalyticsPage
from ui.pages.dashboard import DashboardPage
from ui.pages.history import HistoryPage
from ui.pages.gifts import GiftPage
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
    """Livemetry Pulse メインウィンドウ。"""


    def __init__(self):
        settings = Settings.load()

        appearance_mode = str(
            settings.get(
                "appearance_mode",
                "dark",
            )
        ).strip().lower()

        if appearance_mode not in {
            "light",
            "dark",
        }:
            appearance_mode = "dark"

        ctk.set_appearance_mode(
            appearance_mode
        )

        super().__init__()

        self._license_check_running = False
        self._license_online_valid = None
        self._closing = False

        self.title("Livemetry Pulse")
        self.geometry("1280x860")
        self.minsize(1080, 700)

        self.configure(
            fg_color=("#F5F7FB", "#0B1120")
        )

        self.after(
            200,
            self.set_app_icon,
        )

        self.obs = OBSClient()
        self.current_page = None

        # -----------------------------------------------
        # App shell
        # -----------------------------------------------

        container = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=("#F5F7FB", "#0B1120"),
        )
        container.pack(
            fill="both",
            expand=True,
        )

        # -----------------------------------------------
        # Sidebar
        # -----------------------------------------------

        self.sidebar = ctk.CTkFrame(
            container,
            width=220,
            corner_radius=0,
            fg_color=("#FFFFFF", "#101827"),
            border_width=0,
        )
        self.sidebar.pack(
            side="left",
            fill="y",
        )
        self.sidebar.pack_propagate(False)

        brand = ctk.CTkFrame(
            self.sidebar,
            fg_color="transparent",
        )
        brand.pack(
            fill="x",
            padx=18,
            pady=(24, 26),
        )

        ctk.CTkLabel(
            brand,
            text="\u25c9",
            font=("Yu Gothic UI", 25, "bold"),
            text_color=("#2563EB", "#60A5FA"),
        ).pack(
            side="left",
            padx=(0, 9),
        )

        brand_text = ctk.CTkFrame(
            brand,
            fg_color="transparent",
        )
        brand_text.pack(
            side="left",
        )

        ctk.CTkLabel(
            brand_text,
            text="Livemetry",
            font=("Yu Gothic UI", 18, "bold"),
            text_color=("#0F172A", "#F8FAFC"),
        ).pack(
            anchor="w",
        )

        ctk.CTkLabel(
            brand_text,
            text="Pulse",
            font=("Yu Gothic UI", 11, "bold"),
            text_color=("#2563EB", "#60A5FA"),
        ).pack(
            anchor="w",
        )

        nav = ctk.CTkFrame(
            self.sidebar,
            fg_color="transparent",
        )
        nav.pack(
            fill="x",
            padx=12,
        )

        self.nav_buttons = {}

        def create_nav_button(
            key,
            text_value,
            command,
        ):
            button = ctk.CTkButton(
                nav,
                text=text_value,
                anchor="w",
                height=44,
                corner_radius=10,
                fg_color="transparent",
                hover_color=("#F1F5F9", "#1E293B"),
                text_color=("#475569", "#CBD5E1"),
                font=("Yu Gothic UI", 13, "bold"),
                command=command,
            )
            button.pack(
                fill="x",
                pady=3,
            )

            self.nav_buttons[key] = button
            return button

        self.dashboard_button = create_nav_button(
            "dashboard",
            "\u2302   Dashboard",
            self.show_dashboard,
        )

        self.obs_button = create_nav_button(
            "obs",
            "\u25c9   OBS",
            self.show_obs,
        )

        self.ai_button = create_nav_button(
            "ai",
            "\u2726   AI\u5206\u6790",
            self.show_ai,
        )

        self.history_button = create_nav_button(
            "history",
            "\u25a3   \u5c65\u6b74",
            self.show_history,
        )

        self.analytics_button = create_nav_button(
            "analytics",
            "\u25a4   Analytics",
            self.show_analytics,
        )

        # GiftPage???????
        # ????Dashboard????????????
        # ?????????????????
        self.gifts_button = None

        # -----------------------------------------------
        # Sidebar bottom
        # -----------------------------------------------

        bottom = ctk.CTkFrame(
            self.sidebar,
            fg_color="transparent",
        )
        bottom.pack(
            side="bottom",
            fill="x",
            padx=12,
            pady=(0, 18),
        )

        self.license_label = ctk.CTkLabel(
            bottom,
            text="\u30e9\u30a4\u30bb\u30f3\u30b9\u78ba\u8a8d\u4e2d",
            anchor="w",
            font=("Yu Gothic UI", 10, "bold"),
            text_color=("#64748B", "#94A3B8"),
        )
        self.license_label.pack(
            fill="x",
            padx=10,
            pady=(0, 10),
        )

        self.settings_button = ctk.CTkButton(
            bottom,
            text="\u2699   Settings",
            anchor="w",
            height=44,
            corner_radius=10,
            fg_color="transparent",
            hover_color=("#F1F5F9", "#1E293B"),
            text_color=("#475569", "#CBD5E1"),
            font=("Yu Gothic UI", 13, "bold"),
            command=self.show_settings,
        )
        self.settings_button.pack(
            fill="x",
        )

        self.nav_buttons["settings"] = (
            self.settings_button
        )

        # -----------------------------------------------
        # Main content
        # -----------------------------------------------

        self.content = ctk.CTkFrame(
            container,
            corner_radius=0,
            fg_color=("#F5F7FB", "#0B1120"),
        )
        self.content.pack(
            side="left",
            fill="both",
            expand=True,
        )

        self.show_dashboard()

        self.refresh_license_status()

        self.protocol(
            "WM_DELETE_WINDOW",
            self.on_close,
        )

    def set_app_icon(self):
        """アプリのタイトルバーアイコンを設定します。"""
        icon_path = resource_path(
            os.path.join(
                "assets",
                "LivemetryPulse.ico",
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

    def _set_active_nav(self, active_key):
        for key, button in self.nav_buttons.items():
            if key == active_key:
                button.configure(
                    fg_color=("#E8F0FE", "#172554"),
                    hover_color=("#DBEAFE", "#1E3A8A"),
                    text_color=("#1D4ED8", "#93C5FD"),
                )
            else:
                button.configure(
                    fg_color="transparent",
                    hover_color=("#F1F5F9", "#1E293B"),
                    text_color=("#475569", "#CBD5E1"),
                )

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
        self._set_active_nav("dashboard")

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
        self._set_active_nav("obs")

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
        self._set_active_nav("ai")

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
        self._set_active_nav("history")

    def show_gifts(self):
        if not self.require_license():
            return

        self.clear_page()
        self.current_page = GiftPage(
            self.content,
            self.obs,
        )
        self.current_page.pack(
            fill="both",
            expand=True,
        )
        self._set_active_nav(None)

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
        self._set_active_nav("analytics")

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

        self._set_active_nav("settings")

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