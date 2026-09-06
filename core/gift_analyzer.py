from pathlib import Path
from typing import Any

from core.ai_client import AIClient
from core.gift_calculator import GiftCalculator
from core.gift_catalog import GiftCatalog
from core.gift_detection_parser import GiftDetectionParser
from core.gift_detection_prompt import GIFT_DETECTION_PROMPT
from core.history import HistoryDB


class GiftAnalyzer:
    def __init__(
        self,
        catalog_path: str | Path,
        min_confidence: float = 0.80,
        history_db: HistoryDB | None = None,
        ai_client: AIClient | None = None,
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
        self.ai_client = ai_client or AIClient()

    def analyze_image(
        self,
        image_path: str | Path,
    ) -> dict[str, Any]:
        raw_answer = self.ai_client.analyze_image(
            image_path,
            GIFT_DETECTION_PROMPT,
        )

        return self.analyze_response(
            raw_answer,
            image_path=image_path,
        )

    def analyze_response(
        self,
        raw_answer: str,
        image_path: str | Path | None = None,
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
                    image_path=(
                        str(image_path)
                        if image_path is not None
                        else None
                    ),
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
