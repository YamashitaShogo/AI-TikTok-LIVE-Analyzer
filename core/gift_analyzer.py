from pathlib import Path
from typing import Any

from core.gift_calculator import GiftCalculator
from core.gift_catalog import GiftCatalog
from core.gift_detection_parser import GiftDetectionParser
from core.history import HistoryDB


class GiftAnalyzer:
    def __init__(
        self,
        catalog_path: str | Path,
        min_confidence: float = 0.80,
        history_db: HistoryDB | None = None,
    ):
        self.catalog = GiftCatalog(
            catalog_path
        )

        self.calculator = GiftCalculator(
            self.catalog
        )

        self.min_confidence = max(
            0.0,
            min(
                1.0,
                float(min_confidence),
            ),
        )

        self.history_db = history_db

    def analyze_response(
        self,
        raw_answer: str,
    ) -> dict[str, Any]:
        detections = GiftDetectionParser.parse(
            raw_answer
        )

        accepted = [
            detection
            for detection in detections
            if detection["confidence"]
            >= self.min_confidence
        ]

        ignored = [
            detection
            for detection in detections
            if detection["confidence"]
            < self.min_confidence
        ]

        calculation = self.calculator.calculate_many(
            accepted
        )

        history_ids: list[int] = []

        if self.history_db is not None:
            for detection, item in zip(
                accepted,
                calculation["items"],
            ):
                history_id = self.history_db.save_gift(
                    gift_id=item["gift_id"],
                    gift_name=item["name"],
                    quantity=item["quantity"],
                    coins_each=item["coins_each"],
                    total_coins=item["total_coins"],
                    confidence=detection["confidence"],
                    is_known=item["found"],
                )

                history_ids.append(
                    history_id
                )

        return {
            "detections": detections,
            "accepted_detections": accepted,
            "ignored_detections": ignored,
            "items": calculation["items"],
            "total_coins": calculation["total_coins"],
            "unknown_count": calculation["unknown_count"],
            "history_ids": history_ids,
        }
