import json
import os
import tempfile
import time


class SettingsSaveError(OSError):
    """Raised when settings.json could not be saved even after
    retries. The previously saved settings file is left untouched."""


# Windows transient replace failures worth retrying: the destination
# is briefly held by another reader (another Pulse process, the
# collector, antivirus, sync tools). WinError 5 (access denied) and
# WinError 32 (sharing violation) usually clear within a second.
_REPLACE_RETRY_WINERRORS = (5, 32)
_REPLACE_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.2)


def _is_transient_replace_error(exc):
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, 'winerror', None)
    return winerror in _REPLACE_RETRY_WINERRORS


def replace_with_retry(src, dst):
    """os.replace with retries for transient Windows sharing errors.

    Returns True on success. Raises the last OSError when the error
    is not transient or the retries are exhausted; in that case dst
    (the existing settings file) is guaranteed untouched, because a
    failed replace never modifies the destination.
    """
    last_error = None
    for attempt in range(len(_REPLACE_DELAYS) + 1):
        try:
            os.replace(src, dst)
            return True
        except OSError as exc:
            last_error = exc
            if not _is_transient_replace_error(exc):
                raise
            if attempt < len(_REPLACE_DELAYS):
                time.sleep(_REPLACE_DELAYS[attempt])
    raise last_error


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

            # 完成したファイルと安全に置き換える。一時的な占有
            # (WinError 5 等) では再試行し、それでも置換できない
            # 場合は既存の設定ファイルを一切変更せず
            # SettingsSaveError を送出する。
            try:
                replace_with_retry(temp_path, file_path)
            except OSError as exc:
                raise SettingsSaveError(
                    f"設定を保存できませんでした（既存の設定は変更されていません）: {exc}"
                ) from exc

            return True

        except Exception:
            # 一時ファイルが残っていたら削除
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

            raise