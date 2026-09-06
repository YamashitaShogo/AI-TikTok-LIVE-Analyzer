from pathlib import Path
from typing import Any

from core.gift_calculator import GiftCalculator
from core.gift_catalog import GiftCatalog
from core.gift_detection_parser import GiftDetectionParser


class GiftAnalyzer:
    def __init__(
        self,
        catalog_path: str | Path,
        min_confidence: float = 0.80,
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

        return {
            "detections": detections,
            "accepted_detections": accepted,
            "ignored_detections": ignored,
            "items": calculation["items"],
            "total_coins": calculation["total_coins"],
            "unknown_count": calculation["unknown_count"],
        }
