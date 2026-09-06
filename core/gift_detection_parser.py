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

            sender_value = detection.get(
                "sender_text"
            )

            if sender_value is None:
                sender_text = None
            else:
                sender_text = str(
                    sender_value
                ).strip()

                if not sender_text:
                    sender_text = None

            bbox = None
            bbox_value = detection.get(
                "bbox"
            )

            if (
                isinstance(
                    bbox_value,
                    (list, tuple),
                )
                and len(bbox_value) == 4
            ):
                try:
                    x, y, width, height = [
                        float(value)
                        for value in bbox_value
                    ]

                    if (
                        0.0 <= x <= 1.0
                        and 0.0 <= y <= 1.0
                        and 0.0 < width <= 1.0
                        and 0.0 < height <= 1.0
                    ):
                        width = min(
                            width,
                            1.0 - x,
                        )
                        height = min(
                            height,
                            1.0 - y,
                        )

                        if (
                            width > 0.0
                            and height > 0.0
                        ):
                            bbox = [
                                x,
                                y,
                                width,
                                height,
                            ]
                except (TypeError, ValueError):
                    bbox = None

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
                "sender_text": sender_text,
                "bbox": bbox,
                "confidence": confidence,
            })

        return normalized
