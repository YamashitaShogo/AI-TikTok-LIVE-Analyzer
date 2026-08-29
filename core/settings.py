import json
import os
import tempfile


class Settings:
    """
    Livemetry Pulse 設定管理

    設定ファイルはWindowsのユーザー用AppDataに保存します。

    保存先:
    C:\\Users\\ユーザー名\\AppData\\Local\\AI-TikTok-LIVE-Analyzer\\settings.json
    """

    APP_NAME = "AI-TikTok-LIVE-Analyzer"

    @staticmethod
    def get_settings_dir():
        # Windows の LocalAppData を取得
        base_dir = os.getenv("LOCALAPPDATA")

        # 念のため LOCALAPPDATA が取得できなかった場合
        if not base_dir:
            base_dir = os.path.join(
                os.path.expanduser("~"),
                "AppData",
                "Local"
            )

        settings_dir = os.path.join(
            base_dir,
            Settings.APP_NAME
        )

        # フォルダが無ければ作成
        os.makedirs(
            settings_dir,
            exist_ok=True
        )

        return settings_dir

    @staticmethod
    def get_file_path():
        return os.path.join(
            Settings.get_settings_dir(),
            "settings.json"
        )

    @staticmethod
    def load():
        file_path = Settings.get_file_path()

        if not os.path.exists(file_path):
            return {}

        try:
            with open(
                file_path,
                "r",
                encoding="utf-8"
            ) as f:
                data = json.load(f)

            if isinstance(data, dict):
                return data

            return {}

        except (
            json.JSONDecodeError,
            OSError,
            PermissionError
        ):
            return {}

    @staticmethod
    def save(data):
        settings_dir = Settings.get_settings_dir()
        file_path = Settings.get_file_path()

        temp_path = None

        try:
            # AppData内に一時ファイルを作成
            fd, temp_path = tempfile.mkstemp(
                prefix="settings_",
                suffix=".tmp",
                dir=settings_dir
            )

            # JSONを書き込み
            with os.fdopen(
                fd,
                "w",
                encoding="utf-8"
            ) as f:
                json.dump(
                    data,
                    f,
                    indent=4,
                    ensure_ascii=False
                )

                f.flush()
                os.fsync(f.fileno())

            # 完成したファイルと安全に置き換える
            os.replace(
                temp_path,
                file_path
            )

            return True

        except Exception:
            # 一時ファイルが残っていたら削除
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

            raise