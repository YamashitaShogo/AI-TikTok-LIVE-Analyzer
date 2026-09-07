import queue
import threading
import time
from pathlib import Path
from typing import Any

from core.gift_obs_monitor import GiftOBSMonitor


class GiftMonitorWorker:
    """
    Capture OBS frames independently from AI analysis.

    Capture thread:
        OBS -> unique screenshot -> capture backlog

    Analysis thread:
        capture backlog -> frame gate -> AI / pending queue

    This prevents a slow AI request from stopping OBS capture.
    """

    def __init__(
        self,
        monitor: GiftOBSMonitor,
        capture_interval_seconds: float = 1.0,
        max_capture_backlog: int = 30,
        capture_directory: str | Path = "images/gift_capture_spool",
    ):
        if capture_interval_seconds <= 0:
            raise ValueError(
                "capture_interval_seconds must be greater than 0"
            )

        if max_capture_backlog <= 0:
            raise ValueError(
                "max_capture_backlog must be greater than 0"
            )

        self.monitor = monitor
        self.obs = monitor.obs
        self.controller = monitor.controller
        self.candidate_queue = monitor.candidate_queue

        self.capture_interval_seconds = (
            capture_interval_seconds
        )

        self.capture_directory = Path(
            capture_directory
        )

        self.capture_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._capture_queue = queue.Queue(
            maxsize=max_capture_backlog
        )

        self._event_queue = queue.Queue()

        self._stop_event = threading.Event()
        self._capture_thread = None
        self._analysis_thread = None

        self._running = False
        self._state_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._running

    @property
    def capture_backlog_count(self) -> int:
        return self._capture_queue.qsize()

    @property
    def pending_count(self) -> int:
        return len(
            self.candidate_queue
        )

    def start(self) -> bool:
        with self._state_lock:
            if self._running:
                return False

            existing_threads = (
                self._capture_thread,
                self._analysis_thread,
            )

            if any(
                thread is not None
                and thread.is_alive()
                for thread in existing_threads
            ):
                return False

            if self.obs is None:
                return False

            if not self.obs.is_connected():
                return False

            self._running = True

        self._stop_event.clear()

        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name="GiftCaptureWorker",
            daemon=True,
        )

        self._analysis_thread = threading.Thread(
            target=self._analysis_loop,
            name="GiftAnalysisWorker",
            daemon=True,
        )

        self._capture_thread.start()
        self._analysis_thread.start()

        self._emit(
            "started",
            capture_interval_seconds=(
                self.capture_interval_seconds
            ),
        )

        return True

    def stop(
        self,
        wait: bool = False,
        timeout: float = 5.0,
    ) -> None:
        self._stop_event.set()

        with self._state_lock:
            self._running = False

        if wait:
            threads = (
                self._capture_thread,
                self._analysis_thread,
            )

            for thread in threads:
                if (
                    thread is not None
                    and thread.is_alive()
                ):
                    thread.join(
                        timeout=timeout
                    )

        self._clear_capture_backlog()

        self._emit(
            "stopped",
        )

    def _clear_capture_backlog(self) -> None:
        while True:
            try:
                image_path = (
                    self._capture_queue.get_nowait()
                )
            except queue.Empty:
                break

            self._delete_file(
                image_path
            )

    def get_event_nowait(
        self,
    ) -> dict[str, Any] | None:
        try:
            return self._event_queue.get_nowait()
        except queue.Empty:
            return None

    def _emit(
        self,
        event_type: str,
        **data,
    ) -> None:
        self._event_queue.put(
            {
                "type": event_type,
                **data,
            }
        )

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            started_at = time.monotonic()

            try:
                self._capture_once()
            except Exception as exc:
                self._emit(
                    "capture_error",
                    error=str(exc),
                )

            elapsed = (
                time.monotonic()
                - started_at
            )

            wait_seconds = max(
                0.0,
                self.capture_interval_seconds
                - elapsed,
            )

            self._stop_event.wait(
                wait_seconds
            )

    def _capture_once(self) -> None:
        if self.obs is None:
            self._emit(
                "capture_skipped",
                reason="obs_missing",
            )
            return

        if not self.obs.is_connected():
            self._emit(
                "capture_skipped",
                reason="obs_not_connected",
            )
            return

        scene = self.obs.get_current_scene()

        if not scene:
            self._emit(
                "capture_skipped",
                reason="scene_unavailable",
            )
            return

        filename = (
            f"gift_capture_"
            f"{time.time_ns()}.png"
        )

        requested_path = (
            self.capture_directory
            / filename
        )

        saved = self.obs.save_screenshot(
            scene,
            str(requested_path),
        )

        if not saved:
            self._emit(
                "capture_error",
                error="screenshot_failed",
            )
            return

        resolved_path = Path(
            self.obs.resolve_screenshot_path(
                str(requested_path)
            )
        )

        if (
            not resolved_path.exists()
            or resolved_path.stat().st_size <= 0
        ):
            self._emit(
                "capture_error",
                error="screenshot_missing",
            )
            return

        with self._state_lock:
            if (
                not self._running
                or self._stop_event.is_set()
            ):
                self._delete_file(
                    resolved_path
                )
                return

            try:
                self._capture_queue.put_nowait(
                    resolved_path
                )

            except queue.Full:
                dropped_path = None

                try:
                    dropped_path = (
                        self._capture_queue.get_nowait()
                    )
                except queue.Empty:
                    pass

                if dropped_path is not None:
                    self._delete_file(
                        dropped_path
                    )

                self._capture_queue.put_nowait(
                    resolved_path
                )

                self._emit(
                    "capture_backlog_overflow",
                    dropped_path=(
                        str(dropped_path)
                        if dropped_path is not None
                        else None
                    ),
                    backlog=(
                        self.capture_backlog_count
                    ),
                )

            self._emit(
                "captured",
                path=str(resolved_path),
                backlog=(
                    self.capture_backlog_count
                ),
            )

    def _analysis_loop(self) -> None:
        while not self._stop_event.is_set():
            self._retry_pending_once()

            try:
                image_path = (
                    self._capture_queue.get(
                        timeout=0.2
                    )
                )
            except queue.Empty:
                continue

            try:
                result = (
                    self.controller.process_image(
                        image_path
                    )
                )

                queue_result = None

                if result.get(
                    "blocked_by_rate_limit"
                ):
                    queue_result = (
                        self.candidate_queue.enqueue(
                            image_path
                        )
                    )

                self._emit(
                    "analysis_result",
                    path=str(image_path),
                    result=result,
                    queue_result=queue_result,
                    backlog=(
                        self.capture_backlog_count
                    ),
                    pending_count=(
                        self.pending_count
                    ),
                )

            except Exception as exc:
                queue_result = (
                    self.candidate_queue.enqueue(
                        image_path
                    )
                )

                self._emit(
                    "analysis_error",
                    path=str(image_path),
                    error=str(exc),
                    queue_result=queue_result,
                )

            finally:
                self._delete_file(
                    image_path
                )

    def _retry_pending_once(self) -> None:
        pending_path = (
            self.candidate_queue.peek()
        )

        if pending_path is None:
            return

        if not pending_path.exists():
            self.candidate_queue.acknowledge()

            self._emit(
                "pending_missing",
                path=str(pending_path),
            )
            return

        if not self.controller.rate_limiter.can_call():
            return

        try:
            result = (
                self.controller.process_candidate_image(
                    pending_path
                )
            )
        except Exception as exc:
            self._emit(
                "pending_error",
                path=str(pending_path),
                error=str(exc),
            )
            return

        if not result["analyzed"]:
            return

        processed_path = (
            self.candidate_queue.acknowledge()
        )

        self._emit(
            "pending_result",
            path=str(processed_path),
            result=result,
            pending_count=(
                self.pending_count
            ),
        )

    @staticmethod
    def _delete_file(
        path: str | Path,
    ) -> None:
        path = Path(path)

        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass