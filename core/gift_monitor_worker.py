from __future__ import annotations

import os
import queue
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from core.gift_candidate_queue import GiftCandidateQueue


class GiftMonitorWorker:
    """TikTok Viewer の latest.jpg を監視してギフト分析へ渡す。"""

    MAX_SOURCE_AGE_SECONDS = 15.0

    def __init__(
        self,
        controller,
        source_image_path: str | Path | None = None,
        capture_interval_seconds: float = 1.0,
        max_capture_backlog: int = 30,
        capture_directory: str | Path | None = None,
        pending_directory: str | Path | None = None,
    ):
        if capture_interval_seconds <= 0:
            raise ValueError(
                "capture_interval_seconds must be greater than 0"
            )

        if max_capture_backlog <= 0:
            raise ValueError(
                "max_capture_backlog must be greater than 0"
            )

        base = (
            Path(
                os.environ.get(
                    "LOCALAPPDATA",
                    str(Path.home()),
                )
            )
            / "AI-TikTok-LIVE-Analyzer"
        )

        self.source_image_path = Path(
            source_image_path
            or (base / "capture" / "latest.jpg")
        )

        self.capture_directory = Path(
            capture_directory
            or (base / "gift_capture_spool")
        )
        self.capture_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.controller = controller
        self.candidate_queue = GiftCandidateQueue(
            directory=(
                pending_directory
                or (base / "gift_pending")
            ),
            max_items=max_capture_backlog,
        )

        self.capture_interval_seconds = float(
            capture_interval_seconds
        )

        self._capture_queue = queue.Queue(
            maxsize=max_capture_backlog
        )
        self._event_queue = queue.Queue()

        self._stop_event = threading.Event()
        self._shutdown_requested = False
        self._capture_thread = None
        self._analysis_thread = None

        self._running = False
        self._state_lock = threading.Lock()
        self._last_source_mtime_ns: int | None = None

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._running

    @property
    def capture_backlog_count(self) -> int:
        return self._capture_queue.qsize()

    @property
    def pending_count(self) -> int:
        return len(self.candidate_queue)

    def _source_is_available(self) -> bool:
        path = self.source_image_path

        try:
            if not path.exists():
                return False

            stat = path.stat()

            if stat.st_size <= 0:
                return False

            age = max(
                0.0,
                time.time() - stat.st_mtime,
            )

            return age <= self.MAX_SOURCE_AGE_SECONDS

        except OSError:
            return False

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

            if not self._source_is_available():
                return False

            self._running = True

        self._shutdown_requested = False
        self._stop_event.clear()
        self._last_source_mtime_ns = None

        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name="GiftViewerCaptureWorker",
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
            source_path=str(self.source_image_path),
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
            for thread in (
                self._capture_thread,
                self._analysis_thread,
            ):
                if (
                    thread is not None
                    and thread.is_alive()
                ):
                    thread.join(timeout=timeout)

        self._clear_capture_backlog()
        self._emit("stopped")

    def shutdown(
        self,
        wait: bool = False,
        timeout: float = 5.0,
    ) -> None:
        self._shutdown_requested = True
        self.stop(
            wait=wait,
            timeout=timeout,
        )

        analysis_thread = self._analysis_thread
        if (
            analysis_thread is None
            or not analysis_thread.is_alive()
        ):
            self.candidate_queue.clear()

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
        source = self.source_image_path

        if not source.exists():
            self._emit(
                "capture_skipped",
                reason="viewer_image_missing",
            )
            return

        try:
            stat = source.stat()
        except OSError as exc:
            self._emit(
                "capture_error",
                error=str(exc),
            )
            return

        if stat.st_size <= 0:
            self._emit(
                "capture_skipped",
                reason="viewer_image_empty",
            )
            return

        age = max(
            0.0,
            time.time() - stat.st_mtime,
        )

        if age > self.MAX_SOURCE_AGE_SECONDS:
            self._emit(
                "capture_skipped",
                reason="viewer_image_stale",
                age_seconds=age,
            )
            return

        if self._last_source_mtime_ns == stat.st_mtime_ns:
            return

        self._last_source_mtime_ns = stat.st_mtime_ns

        suffix = source.suffix.lower() or ".jpg"
        snapshot = (
            self.capture_directory
            / f"gift_capture_{time.time_ns()}{suffix}"
        )

        shutil.copy2(
            source,
            snapshot,
        )

        if (
            not snapshot.exists()
            or snapshot.stat().st_size <= 0
        ):
            self._emit(
                "capture_error",
                error="viewer_snapshot_missing",
            )
            return

        with self._state_lock:
            if (
                not self._running
                or self._stop_event.is_set()
            ):
                self._delete_file(snapshot)
                return

            try:
                self._capture_queue.put_nowait(
                    snapshot
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
                    snapshot
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
                path=str(snapshot),
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

                if self._stop_event.is_set():
                    continue

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
                if self._stop_event.is_set():
                    continue

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

        if self._shutdown_requested:
            self.candidate_queue.clear()

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

        if self._stop_event.is_set():
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
