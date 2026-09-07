from pathlib import Path
from typing import Any

from core.gift_frame_gate import GiftFrameGate
from core.gift_rate_limiter import GiftRateLimiter
from core.gift_stream_analyzer import GiftStreamAnalyzer


class GiftMonitorController:
    """
    Connect local frame-change detection with stream gift analysis.

    GiftFrameGate decides whether AI analysis is necessary.
    GiftStreamAnalyzer handles AI detection, event tracking,
    coin calculation, and history persistence.
    """

    def __init__(
        self,
        stream_analyzer: GiftStreamAnalyzer,
        frame_gate: GiftFrameGate | None = None,
        rate_limiter: GiftRateLimiter | None = None,
    ):
        self.stream_analyzer = stream_analyzer

        self.frame_gate = (
            frame_gate
            if frame_gate is not None
            else GiftFrameGate(
                analyze_first_frame=True
            )
        )

        self.rate_limiter = (
            rate_limiter
            if rate_limiter is not None
            else GiftRateLimiter(
                max_calls=5,
                window_seconds=60.0,
            )
        )

    def process_image(
        self,
        image_path: str | Path,
    ) -> dict[str, Any]:
        gate_result = self.frame_gate.check_image(
            image_path,
            update_previous=False,
        )

        if not gate_result["should_analyze"]:
            self.frame_gate.accept_image(
                image_path
            )

            return {
                "analyzed": False,
                "blocked_by_rate_limit": False,
                "retry_after_seconds": 0.0,
                "gate": gate_result,
                "analysis": None,
            }

        if not self.rate_limiter.can_call():
            return {
                "analyzed": False,
                "blocked_by_rate_limit": True,
                "retry_after_seconds": (
                    self.rate_limiter.seconds_until_available()
                ),
                "gate": gate_result,
                "analysis": None,
            }

        self.rate_limiter.record_call()

        analysis = (
            self.stream_analyzer.analyze_image(
                image_path
            )
        )

        # Only consume the candidate after AI analysis succeeded.
        self.frame_gate.accept_image(
            image_path
        )

        return {
            "analyzed": True,
            "blocked_by_rate_limit": False,
            "retry_after_seconds": 0.0,
            "gate": gate_result,
            "analysis": analysis,
        }

    def reset(self) -> None:
        self.frame_gate.reset()
        self.stream_analyzer.reset()
        self.rate_limiter.reset()