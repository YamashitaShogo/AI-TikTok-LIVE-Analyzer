import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


APP_NAME = "AI-TikTok-LIVE-Analyzer"


class ViewerCollectorManager:
    """
    Starts/stops the TikTok pywebview collector as a child process.

    Development behavior:
      - uses the same Python interpreter as Livemetry Pulse
      - opens no extra console window on Windows
      - writes collector stdout/stderr to AppData logs
    """

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._log_handle = None

    @staticmethod
    def _collector_script() -> Path:
        return Path(__file__).resolve().parent / "viewer_collector.py"

    @staticmethod
    def _log_path() -> Path:
        base = os.getenv("LOCALAPPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Local")

        log_dir = Path(base) / APP_NAME / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "viewer_collector.log"

    def is_running(self) -> bool:
        return (
            self._process is not None
            and self._process.poll() is None
        )

    def start(self) -> bool:
        if self.is_running():
            return False

        if getattr(sys, "frozen", False):
            command = [
                sys.executable,
                "--viewer-collector",
            ]
            working_directory = str(
                Path(sys.executable).resolve().parent
            )
        else:
            script = self._collector_script()

            if not script.exists():
                raise FileNotFoundError(
                    f"TikTok Viewer Collector not found: {script}"
                )

            command = [
                sys.executable,
                "-u",
                str(script),
            ]
            working_directory = str(
                script.parent.parent
            )

        log_path = self._log_path()
        self._log_handle = open(
            log_path,
            "a",
            encoding="utf-8",
            buffering=1,
        )

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            )

        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONUTF8"] = "1"

        self._process = subprocess.Popen(
            command,
            cwd=working_directory,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            env=child_env,
        )

        return True

    def stop(self) -> None:
        process = self._process
        self._process = None

        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None
