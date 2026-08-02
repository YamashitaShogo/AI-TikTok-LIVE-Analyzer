import json
import logging
import os
import sys
import traceback
from pathlib import Path
from tkinter import messagebox

from core.license_client import LicenseClient
from ui.license_window import LicenseWindow
from ui.main_window import MainWindow


APP_NAME = "AI-TikTok-LIVE-Analyzer"


def get_log_directory() -> Path:
    """ログ保存先を返す。必要ならフォルダも自動作成する。"""
    if getattr(sys, "frozen", False):
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            log_dir = Path(local_app_data) / APP_NAME / "logs"
        else:
            log_dir = Path.home() / APP_NAME / "logs"
    else:
        project_root = Path(__file__).resolve().parent
        log_dir = project_root / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_settings_path() -> Path:
    """settings.json の保存先を返す。"""
    base = os.getenv("LOCALAPPDATA")

    if not base:
        base = os.path.join(
            os.path.expanduser("~"),
            "AppData",
            "Local",
        )

    settings_dir = Path(base) / APP_NAME
    settings_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return settings_dir / "settings.json"


LOG_DIR = get_log_directory()
LOG_FILE = LOG_DIR / "app.log"


def setup_logging() -> None:
    """ファイルとコンソールへログを出力する。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(
                LOG_FILE,
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
        force=True,
    )

    logging.info("=" * 70)
    logging.info("アプリを起動しました")
    logging.info("ログ保存先: %s", LOG_FILE)


def show_error_dialog(
    title: str = "エラーが発生しました",
) -> None:
    """ユーザー向けのエラーダイアログを表示する。"""
    message = (
        "予期しないエラーが発生しました。\n\n"
        "エラーの詳細はログファイルに保存されています。\n\n"
        f"ログ保存先:\n{LOG_FILE}"
    )

    try:
        messagebox.showerror(
            title,
            message,
        )
    except Exception:
        logging.exception(
            "エラーダイアログの表示に失敗しました"
        )


def handle_unhandled_exception(
    exc_type,
    exc_value,
    exc_traceback,
) -> None:
    """Python全体で処理されなかった例外を記録する。"""
    if issubclass(
        exc_type,
        KeyboardInterrupt,
    ):
        sys.__excepthook__(
            exc_type,
            exc_value,
            exc_traceback,
        )
        return

    logging.critical(
        "未処理の例外が発生しました",
        exc_info=(
            exc_type,
            exc_value,
            exc_traceback,
        ),
    )

    traceback.print_exception(
        exc_type,
        exc_value,
        exc_traceback,
    )

    show_error_dialog()


def handle_tkinter_exception(
    exc_type,
    exc_value,
    exc_traceback,
) -> None:
    """Tkinter内で発生した例外を記録する。"""
    logging.error(
        "画面操作中に例外が発生しました",
        exc_info=(
            exc_type,
            exc_value,
            exc_traceback,
        ),
    )

    traceback.print_exception(
        exc_type,
        exc_value,
        exc_traceback,
    )

    show_error_dialog(
        "画面操作中にエラーが発生しました"
    )


def load_saved_license_key() -> str:
    """保存済みライセンスキーを読み込む。"""
    path = get_settings_path()

    if not path.exists():
        return ""

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            settings = json.load(file)

        if not isinstance(
            settings,
            dict,
        ):
            return ""

        return str(
            settings.get(
                "license_key",
                "",
            )
        ).strip()

    except (
        OSError,
        json.JSONDecodeError,
    ):
        logging.exception(
            "保存済みライセンス情報を読み込めませんでした"
        )
        return ""


def verify_saved_license() -> bool:
    """保存済みライセンスをRenderで再認証する。"""
    key = load_saved_license_key()

    if not key:
        logging.info(
            "保存済みライセンスキーがありません"
        )
        return False

    logging.info(
        "保存済みライセンスを確認します"
    )

    result = LicenseClient.verify(
        key
    )

    if result.get(
        "valid",
        False,
    ):
        logging.info(
            "ライセンス認証成功"
        )
        return True

    logging.warning(
        "ライセンス認証失敗: %s",
        result.get(
            "status",
            "unknown",
        ),
    )

    return False


def show_license_window() -> bool:
    """ライセンス入力画面を表示する。"""
    logging.info(
        "ライセンス認証画面を表示します"
    )

    license_app = LicenseWindow()

    license_app.report_callback_exception = (
        handle_tkinter_exception
    )

    license_app.mainloop()

    return bool(
        license_app.authenticated
    )


def start_main_window() -> None:
    """メイン画面を起動する。"""
    app = MainWindow()

    app.report_callback_exception = (
        handle_tkinter_exception
    )

    logging.info(
        "メイン画面を表示します"
    )

    app.mainloop()

    logging.info(
        "アプリを正常終了しました"
    )


def main() -> None:
    setup_logging()

    sys.excepthook = (
        handle_unhandled_exception
    )

    try:
        authenticated = (
            verify_saved_license()
        )

        if not authenticated:
            authenticated = (
                show_license_window()
            )

        if not authenticated:
            logging.warning(
                "ライセンス未認証のため終了します"
            )
            return

        start_main_window()

    except Exception:
        logging.exception(
            "アプリの起動または実行中に"
            "致命的なエラーが発生しました"
        )

        show_error_dialog(
            "アプリを起動できませんでした"
        )

        raise


if __name__ == "__main__":
    main()