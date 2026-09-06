import json
import re
from typing import Any


class GiftDetectionParser:
    @staticmethod
    def parse(raw_answer: str) -> list[dict[str, Any]]:
        match = re.search(
            r"\{.*\}",
            str(raw_answer),
            flags=re.DOTALL,
        )

        if not match:
            raise ValueError(
                "Gift detection response did not contain JSON."
            )

        data = json.loads(
            match.group(0)
        )

        detections = data.get(
            "detections",
            [],
        )

        if not isinstance(detections, list):
            raise ValueError(
                "detections must be a list."
            )

        normalized = []

        for detection in detections:
            if not isinstance(detection, dict):
                continue

            gift_id = str(
                detection.get(
                    "gift_id",
                    "unknown",
                )
            ).strip()

            if not gift_id:
                gift_id = "unknown"

            try:
                quantity = int(
                    detection.get(
                        "quantity",
                        1,
                    )
                )
            except (TypeError, ValueError):
                quantity = 1

            quantity = max(
                1,
                quantity,
            )

            try:
                confidence = float(
                    detection.get(
                        "confidence",
                        0.0,
                    )
                )
            except (TypeError, ValueError):
                confidence = 0.0

            confidence = max(
                0.0,
                min(
                    1.0,
                    confidence,
                ),
            )

            normalized.append({
                "gift_id": gift_id,
                "quantity": quantity,
                "confidence": confidence,
            })

        return normalized
