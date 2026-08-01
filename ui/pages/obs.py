import customtkinter as ctk
from core.obs_client import OBSClient
from core.settings import Settings

class OBSPage(ctk.CTkFrame):
    def __init__(self, parent, obs):
        self.obs = obs
        super().__init__(parent)

        title = ctk.CTkLabel(
            self,
            text="📡 OBS設定",
            font=("Yu Gothic UI", 24, "bold")
        )
        title.pack(pady=20)

        # ホスト
        ctk.CTkLabel(
            self,
            text="ホスト"
        ).pack(anchor="w", padx=20)

        self.host_entry = ctk.CTkEntry(self, width=300)
        self.host_entry.insert(0, "localhost")
        self.host_entry.pack(anchor="w", padx=20, pady=(0, 10))

        # ポート
        ctk.CTkLabel(
            self,
            text="ポート"
        ).pack(anchor="w", padx=20)

        self.port_entry = ctk.CTkEntry(self, width=300)
        self.port_entry.insert(0, "4455")
        self.port_entry.pack(anchor="w", padx=20, pady=(0, 10))

        # パスワード
        ctk.CTkLabel(
            self,
            text="パスワード"
        ).pack(anchor="w", padx=20)

        self.password_entry = ctk.CTkEntry(
            self,
            width=300,
            show="*"
        )
        self.password_entry.pack(anchor="w", padx=20, pady=(0, 20))

        self.status = ctk.CTkLabel(
            self,
            text="状態：未接続"
        )
        self.status.pack(pady=10)

        ctk.CTkButton(
            self,
            text="接続テスト",
            width=200,
            command=self.test_connection
        ).pack(pady=10)

        ctk.CTkButton(
            self,
            text="現在のシーンを取得",
            width=200,
            command=self.get_scene
        ).pack(pady=10)

        ctk.CTkButton(
            self,
            text="配信状態を取得",
            width=200,
            command=self.get_stream_status
        ).pack(pady=10)

        ctk.CTkButton(
            self,
            text="録画状態を取得",
            width=200,
            command=self.get_record_status
        ).pack(pady=10)

        ctk.CTkButton(
            self,
            text="ソース一覧を取得",
            width=200,
            command=self.get_sources
        ).pack(pady=10)

        ctk.CTkButton(
            self,
            text="スクリーンショット取得",
            width=200,
            command=self.save_screenshot
        ).pack(pady=5)

        ctk.CTkButton(
            self,
            text="設定を保存",
            width=200,
            command=self.save_settings
        ).pack(pady=10)


        settings = Settings.load()

        self.host_entry.delete(0, "end")
        self.host_entry.insert(0, settings.get("host", "localhost"))

        self.port_entry.delete(0, "end")
        self.port_entry.insert(0, settings.get("port", "4455"))

        self.password_entry.delete(0, "end")
        self.password_entry.insert(0, settings.get("password", ""))

    def test_connection(self):
        ok = self.obs.connect(
            self.host_entry.get(),
            self.port_entry.get(),
            self.password_entry.get()
        )

        if ok:
            self.status.configure(
                text="状態：接続成功 ✅"
            )
        else:
            self.status.configure(
                text="状態：接続失敗 ❌"
            )
    def save_settings(self):
        Settings.save({
            "host": self.host_entry.get(),
            "port": self.port_entry.get(),
            "password": self.password_entry.get()
        })

        self.status.configure(
            text="状態：設定を保存しました ✅"
        )

    def get_scene(self):
        scene = self.obs.get_current_scene()

        if scene is None:
            self.status.configure(
                text="状態：シーン取得失敗 ❌"
            )
        else:
            self.status.configure(
                text=f"現在のシーン：{scene}"
            )

    def get_stream_status(self):
        streaming = self.obs.is_streaming()

        if streaming is None:
            self.status.configure(
                text="状態：取得失敗 ❌"
            )
        elif streaming:
            self.status.configure(
                text="🔴 配信中"
            )
        else:
            self.status.configure(
                text="⚪ 配信していません"
            )
    
    def get_record_status(self):
        recording = self.obs.is_recording()

        if recording is None:
            self.status.configure(
                text="状態：取得失敗 ❌"
            )
        elif recording:
            self.status.configure(
                text="⏺️ 録画中"
            )
        else:
            self.status.configure(
                text="⏹️ 録画していません"
            )
    
    def get_sources(self):
        sources = self.obs.get_sources()

        if sources is None:
            self.status.configure(
                text="ソース取得失敗 ❌"
            )
        else:
            self.status.configure(
                text="ソース: " + ", ".join(sources)
            )

    def save_screenshot(self):
        scene = self.obs.get_current_scene()

        if scene is None:
            self.status.configure(
                text="シーン取得失敗 ❌"
            )
            return

        result = self.obs.save_screenshot(
            scene,
            "images/current.png"
        )

        if result:
            self.status.configure(
                text="スクリーンショット保存完了 ✅"
            )
        else:
            self.status.configure(
                text="スクリーンショット保存失敗 ❌"
            )