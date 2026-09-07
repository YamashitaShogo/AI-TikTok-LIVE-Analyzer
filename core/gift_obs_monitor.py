from pathlib import Path
from typing import Any

from core.gift_candidate_queue import GiftCandidateQueue
from core.gift_monitor_controller import GiftMonitorController


class GiftOBSMonitor:
    """
    Capture OBS screenshots and pass them to GiftMonitorController.

    Screenshots blocked by the AI rate limit are copied into a
    bounded pending queue so a short-lived candidate is not lost
    when the live screenshot file is overwritten.
    """

    def __init__(
        self,
        obs,
        controller: GiftMonitorController,
        screenshot_path: str = "images/gift_monitor.png",
        candidate_queue: GiftCandidateQueue | None = None,
    ):
        self.obs = obs
        self.controller = controller
        self.screenshot_path = screenshot_path

        self.candidate_queue = (
            candidate_queue
            if candidate_queue is not None
            else GiftCandidateQueue()
        )

    def retry_pending_once(self) -> dict[str, Any]:
        pending_path = self.candidate_queue.peek()

        if pending_path is None:
            return {
                "processed": False,
                "reason": "queue_empty",
                "path": None,
                "result": None,
                "pending_count": 0,
            }

        if not pending_path.exists():
            self.candidate_queue.acknowledge()

            return {
                "processed": False,
                "reason": "candidate_missing",
                "path": str(pending_path),
                "result": None,
                "pending_count": len(
                    self.candidate_queue
                ),
            }

        result = (
            self.controller.process_candidate_image(
                pending_path
            )
        )

        if result["analyzed"]:
            processed_path = (
                self.candidate_queue.acknowledge()
            )

            return {
                "processed": True,
                "reason": "analyzed",
                "path": str(processed_path),
                "result": result,
                "pending_count": len(
                    self.candidate_queue
                ),
            }

        return {
            "processed": False,
            "reason": (
                "rate_limited"
                if result.get(
                    "blocked_by_rate_limit"
                )
                else "not_analyzed"
            ),
            "path": str(pending_path),
            "result": result,
            "pending_count": len(
                self.candidate_queue
            ),
        }

    def poll_once(self) -> dict[str, Any]:
        pending_retry = (
            self.retry_pending_once()
        )

        if self.obs is None:
            return {
                "captured": False,
                "reason": "obs_missing",
                "result": None,
                "pending_retry": pending_retry,
                "pending_count": len(
                    self.candidate_queue
                ),
            }

        if not self.obs.is_connected():
            return {
                "captured": False,
                "reason": "obs_not_connected",
                "result": None,
                "pending_retry": pending_retry,
                "pending_count": len(
                    self.candidate_queue
                ),
            }

        scene = self.obs.get_current_scene()

        if not scene:
            return {
                "captured": False,
                "reason": "scene_unavailable",
                "result": None,
                "pending_retry": pending_retry,
                "pending_count": len(
                    self.candidate_queue
                ),
            }

        saved = self.obs.save_screenshot(
            scene,
            self.screenshot_path,
        )

        if not saved:
            return {
                "captured": False,
                "reason": "screenshot_failed",
                "result": None,
                "pending_retry": pending_retry,
                "pending_count": len(
                    self.candidate_queue
                ),
            }

        resolved_path = (
            self.obs.resolve_screenshot_path(
                self.screenshot_path
            )
        )

        resolved_path = Path(
            resolved_path
        )

        if (
            not resolved_path.exists()
            or resolved_path.stat().st_size <= 0
        ):
            return {
                "captured": False,
                "reason": "screenshot_missing",
                "result": None,
                "pending_retry": pending_retry,
                "pending_count": len(
                    self.candidate_queue
                ),
            }

        result = self.controller.process_image(
            resolved_path
        )

        queue_result = {
            "queued": False,
            "reason": "not_needed",
            "path": None,
            "size": len(
                self.candidate_queue
            ),
        }

        if result.get(
            "blocked_by_rate_limit"
        ):
            queue_result = (
                self.candidate_queue.enqueue(
                    resolved_path
                )
            )

        return {
            "captured": True,
            "reason": "ok",
            "scene": scene,
            "image_path": str(
                resolved_path
            ),
            "result": result,
            "queue": queue_result,
            "pending_retry": pending_retry,
            "pending_count": len(
                self.candidate_queue
            ),
        }

    def reset(self) -> None:
        self.controller.reset()
        self.candidate_queue.clear()