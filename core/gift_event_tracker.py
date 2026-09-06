from typing import Any


class GiftEventTracker:
    """
    Track visible gift events across sequential screenshots.

    This tracker does not use a fixed time-based deduplication window.

    An event remains active while a matching gift is visible in
    consecutive frames. Once it disappears from a frame, a later
    appearance is treated as a new event.
    """

    def __init__(
        self,
        bbox_tolerance: float = 0.15,
    ):
        self.bbox_tolerance = max(
            0.0,
            float(bbox_tolerance),
        )

        self._active_events: dict[
            tuple[str, str | None],
            dict[str, Any],
        ] = {}

    @staticmethod
    def _normalize_sender(
        sender_text: Any,
    ) -> str | None:
        if sender_text is None:
            return None

        value = str(
            sender_text
        ).strip()

        return value or None

    def _event_key(
        self,
        detection: dict[str, Any],
    ) -> tuple[str, str | None]:
        return (
            str(
                detection.get(
                    "gift_id",
                    "unknown",
                )
            ),
            self._normalize_sender(
                detection.get(
                    "sender_text"
                )
            ),
        )

    def _bbox_matches(
        self,
        previous: Any,
        current: Any,
    ) -> bool:
        if previous is None or current is None:
            return True

        if (
            not isinstance(previous, (list, tuple))
            or not isinstance(current, (list, tuple))
            or len(previous) != 4
            or len(current) != 4
        ):
            return True

        try:
            previous_center_x = (
                float(previous[0])
                + float(previous[2]) / 2.0
            )
            previous_center_y = (
                float(previous[1])
                + float(previous[3]) / 2.0
            )

            current_center_x = (
                float(current[0])
                + float(current[2]) / 2.0
            )
            current_center_y = (
                float(current[1])
                + float(current[3]) / 2.0
            )
        except (TypeError, ValueError):
            return True

        return (
            abs(
                previous_center_x
                - current_center_x
            )
            <= self.bbox_tolerance
            and abs(
                previous_center_y
                - current_center_y
            )
            <= self.bbox_tolerance
        )

    def update(
        self,
        detections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Process one screenshot/frame.

        Returns one result per visible detection with:

        - event_quantity: visible cumulative quantity
        - added_quantity: newly counted quantity in this frame
        - is_new_event: whether this starts a new visible event
        """

        results: list[dict[str, Any]] = []
        next_active: dict[
            tuple[str, str | None],
            dict[str, Any],
        ] = {}

        for detection in detections:
            key = self._event_key(
                detection
            )

            try:
                quantity = max(
                    1,
                    int(
                        detection.get(
                            "quantity",
                            1,
                        )
                    ),
                )
            except (TypeError, ValueError):
                quantity = 1

            previous = self._active_events.get(
                key
            )

            same_visible_event = (
                previous is not None
                and self._bbox_matches(
                    previous.get("bbox"),
                    detection.get("bbox"),
                )
            )

            if not same_visible_event:
                added_quantity = quantity
                max_quantity = quantity
                is_new_event = True

            else:
                previous_max_quantity = int(
                    previous.get(
                        "max_quantity",
                        previous.get(
                            "quantity",
                            1,
                        ),
                    )
                )

                if quantity > previous_max_quantity:
                    added_quantity = (
                        quantity
                        - previous_max_quantity
                    )
                    max_quantity = quantity
                else:
                    # Keep the highest quantity already observed
                    # for this visible event. A temporary lower
                    # AI/OCR reading must not reduce the tracked
                    # quantity and cause later double counting.
                    added_quantity = 0
                    max_quantity = previous_max_quantity

                is_new_event = False

            result = dict(
                detection
            )

            result.update({
                "event_quantity": quantity,
                "added_quantity": added_quantity,
                "is_new_event": is_new_event,
            })

            results.append(
                result
            )

            next_active[key] = {
                "quantity": quantity,
                "max_quantity": max_quantity,
                "bbox": detection.get(
                    "bbox"
                ),
            }

        # Anything not visible in this frame is considered ended.
        self._active_events = next_active

        return results

    def reset(self) -> None:
        self._active_events.clear()
