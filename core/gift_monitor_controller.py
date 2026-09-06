from pathlib import Path
from typing import Any

from core.gift_frame_gate import GiftFrameGate
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
    ):
        self.stream_analyzer = stream_analyzer

        self.frame_gate = (
            frame_gate
            if frame_gate is not None
            else GiftFrameGate(
                analyze_first_frame=True
            )
        )

    def process_image(
        self,
        image_path: str | Path,
    ) -> dict[str, Any]:
        gate_result = self.frame_gate.check_image(
            image_path
        )

        if not gate_result["should_analyze"]:
            return {
                "analyzed": False,
                "gate": gate_result,
                "analysis": None,
            }

        analysis = (
            self.stream_analyzer.analyze_image(
                image_path
            )
        )

        return {
            "analyzed": True,
            "gate": gate_result,
            "analysis": analysis,
        }

    def reset(self) -> None:
        self.frame_gate.reset()
        self.stream_analyzer.reset()