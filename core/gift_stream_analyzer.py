from pathlib import Path
from typing import Any

from core.ai_client import AIClient
from core.gift_analyzer import GiftAnalyzer
from core.gift_event_tracker import GiftEventTracker
from core.history import HistoryDB


class GiftStreamAnalyzer:
    """
    Analyze sequential livestream screenshots.

    GiftAnalyzer handles one screenshot.
    GiftEventTracker determines how many newly visible gifts
    should actually be counted.
    """

    def __init__(
        self,
        catalog_path: str | Path,
        min_confidence: float = 0.80,
        history_db: HistoryDB | None = None,
        ai_client: AIClient | None = None,
    ):
        # Important:
        # Single-image analyzer must not save history itself,
        # otherwise stream analysis could double-save gifts.
        self.analyzer = GiftAnalyzer(
            catalog_path=catalog_path,
            min_confidence=min_confidence,
            history_db=None,
            ai_client=ai_client,
        )

        self.tracker = GiftEventTracker()
        self.history_db = history_db

    def analyze_image(
        self,
        image_path: str | Path,
    ) -> dict[str, Any]:
        result = self.analyzer.analyze_image(
            image_path
        )

        return self._process_result(
            result,
            image_path=image_path,
        )

    def analyze_response(
        self,
        raw_answer: str,
        image_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """
        Testable path that skips the real AI request.
        """

        result = self.analyzer.analyze_response(
            raw_answer,
            image_path=None,
        )

        return self._process_result(
            result,
            image_path=image_path,
        )

    def _process_result(
        self,
        result: dict[str, Any],
        image_path: str | Path | None = None,
    ) -> dict[str, Any]:
        accepted = result.get(
            "accepted_detections",
            [],
        )

        tracked = self.tracker.update(
            accepted
        )

        counted_detections: list[
            dict[str, Any]
        ] = []

        for detection in tracked:
            added_quantity = int(
                detection.get(
                    "added_quantity",
                    0,
                )
            )

            if added_quantity <= 0:
                continue

            counted = dict(
                detection
            )

            # Calculator must receive only the newly counted
            # quantity, not the cumulative on-screen multiplier.
            counted["quantity"] = added_quantity

            counted_detections.append(
                counted
            )

        calculation = (
            self.analyzer.calculator.calculate_many(
                counted_detections
            )
        )

        history_ids: list[int] = []

        if self.history_db is not None:
            for detection, item in zip(
                counted_detections,
                calculation["items"],
            ):
                history_id = (
                    self.history_db.save_gift(
                        gift_id=item["gift_id"],
                        gift_name=item["name"],
                        quantity=item["quantity"],
                        coins_each=item["coins_each"],
                        total_coins=item["total_coins"],
                        confidence=detection.get(
                            "confidence"
                        ),
                        is_known=item["found"],
                        image_path=(
                            str(image_path)
                            if image_path is not None
                            else None
                        ),
                        sender_text=detection.get(
                            "sender_text"
                        ),
                        bbox=detection.get(
                            "bbox"
                        ),
                    )
                )

                history_ids.append(
                    history_id
                )

        return {
            "detections": result.get(
                "detections",
                [],
            ),
            "accepted_detections": accepted,
            "ignored_detections": result.get(
                "ignored_detections",
                [],
            ),
            "tracked_detections": tracked,
            "counted_detections": counted_detections,
            "items": calculation["items"],
            "total_coins": calculation[
                "total_coins"
            ],
            "unknown_count": calculation[
                "unknown_count"
            ],
            "history_ids": history_ids,
        }

    def reset(self) -> None:
        self.tracker.reset()
