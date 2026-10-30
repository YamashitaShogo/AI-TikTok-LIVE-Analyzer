import json
import os
import tempfile
import threading
import time


class SettingsSaveError(OSError):
    """Raised when settings.json could not be saved even after
    retries. The previously saved settings file is left untouched."""


class SettingsLoadError(Exception):
    """Raised when settings.json EXISTS but cannot be read or parsed.

    Kept distinct from "file does not exist" (a normal first run):
    an existing-but-unreadable file must never be treated as empty
    settings, because saving on that basis would wipe the license
    key, the registered ID, workspace settings and more.
    """


# Serializes read-modify-write cycles inside this process so two
# writers cannot lose each other's keys (lost update).
_UPDATE_LOCK = threading.Lock()


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
    def file_state():
        """'missing' (first run) | 'ok' | 'unreadable' (exists but
        cannot be read or parsed right now)."""
        file_path = Settings.get_file_path()
        if not os.path.exists(file_path):
            return 'missing'
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return 'ok' if isinstance(data, dict) else 'unreadable'
        except (OSError, ValueError):
            return 'unreadable'

    @staticmethod
    def load_strict():
        """Settings for read-modify-write use.

        Returns {} ONLY when the file does not exist. Raises
        SettingsLoadError when the file exists but cannot be read or
        parsed, so callers abort instead of overwriting real settings
        with defaults/empty values.
        """
        file_path = Settings.get_file_path()
        if not os.path.exists(file_path):
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            raise SettingsLoadError(
                f"既存のsettings.jsonを読み込めませんでした: {exc}") from exc
        if not isinstance(data, dict):
            raise SettingsLoadError(
                "既存のsettings.jsonの形式が不正です（辞書ではありません）")
        return data

    @staticmethod
    def load():
        """Lenient read for display/status purposes.

        Returns {} whenever the file is missing OR unreadable. Never
        use the result as the basis of a save: save() itself refuses
        to overwrite an existing-but-unreadable file, and update()
        reads strictly.
        """
        try:
            return Settings.load_strict()
        except SettingsLoadError:
            return {}

    @staticmethod
    def update(changes):
        """Merge `changes` into the stored settings, safely.

        Reads the current file strictly (aborting with
        SettingsLoadError when it exists but is unreadable), merges,
        and saves — all under a process-wide lock so concurrent
        in-process writers cannot lose each other's keys. When every
        change already matches the stored value, the file is NOT
        rewritten. Returns True when the file was written.
        """
        if not isinstance(changes, dict):
            raise TypeError("changes must be a dict")
        with _UPDATE_LOCK:
            current = Settings.load_strict()
            if all(current.get(key) == value
                   for key, value in changes.items()):
                return False
            merged = dict(current)
            merged.update(changes)
            Settings.save(merged)
            return True

    @staticmethod
    def save(data):
        settings_dir = Settings.get_settings_dir()
        file_path = Settings.get_file_path()

        # Protection: never overwrite an existing settings file that
        # cannot currently be read — its contents (license key,
        # registered ID, workspace settings) would be lost. A missing
        # file (first run) or a readable one is fine to replace.
        if os.path.exists(file_path):
            try:
                Settings.load_strict()
            except SettingsLoadError as exc:
                raise SettingsSaveError(
                    "既存の設定を読み込めなかったため、保護のため保存を中止しました"
                    f"（既存の設定は変更されていません）: {exc}"
                ) from exc

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