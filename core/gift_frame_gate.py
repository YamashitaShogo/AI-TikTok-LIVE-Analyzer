from pathlib import Path
from typing import Any

import cv2
import numpy as np


class GiftFrameGate:
    """
    Lightweight local frame-change detector.
    """

    def __init__(
        self,
        roi=None,
        pixel_diff_threshold=20,
        changed_ratio_threshold=0.08,
        mean_diff_threshold=4.0,
        strong_mean_diff_threshold=12.0,
        analyze_first_frame=True,
        target_width=320,
    ):
        self.roi = roi
        self.pixel_diff_threshold = max(1, int(pixel_diff_threshold))
        self.changed_ratio_threshold = max(
            0.0,
            min(1.0, float(changed_ratio_threshold)),
        )
        self.mean_diff_threshold = max(
            0.0,
            float(mean_diff_threshold),
        )
        self.strong_mean_diff_threshold = max(
            self.mean_diff_threshold,
            float(strong_mean_diff_threshold),
        )
        self.analyze_first_frame = bool(analyze_first_frame)
        self.target_width = max(64, int(target_width))
        self._previous_frame = None

    def _extract_roi(self, frame):
        if self.roi is None:
            return frame

        if len(self.roi) != 4:
            raise ValueError(
                "ROI must contain (x, y, width, height)."
            )

        x, y, width, height = [
            float(value)
            for value in self.roi
        ]

        if (
            x < 0.0
            or y < 0.0
            or width <= 0.0
            or height <= 0.0
            or x >= 1.0
            or y >= 1.0
        ):
            raise ValueError("ROI values are invalid.")

        x2 = min(1.0, x + width)
        y2 = min(1.0, y + height)

        frame_height, frame_width = frame.shape[:2]

        left = int(x * frame_width)
        top = int(y * frame_height)
        right = max(left + 1, int(x2 * frame_width))
        bottom = max(top + 1, int(y2 * frame_height))

        return frame[top:bottom, left:right]

    def _prepare(self, frame):
        if frame is None or frame.size == 0:
            raise ValueError("Frame is empty.")

        roi_frame = self._extract_roi(frame)

        if roi_frame.size == 0:
            raise ValueError("ROI produced an empty frame.")

        gray = cv2.cvtColor(
            roi_frame,
            cv2.COLOR_BGR2GRAY,
        )

        height, width = gray.shape[:2]

        if width != self.target_width:
            scale = self.target_width / float(width)

            target_height = max(
                1,
                int(height * scale),
            )

            gray = cv2.resize(
                gray,
                (self.target_width, target_height),
                interpolation=cv2.INTER_AREA,
            )

        return cv2.GaussianBlur(
            gray,
            (5, 5),
            0,
        )

    def check_frame(
        self,
        frame,
        update_previous: bool = True,
    ) -> dict[str, Any]:
        prepared = self._prepare(frame)

        if self._previous_frame is None:
            if update_previous:
                self._previous_frame = (
                    prepared.copy()
                )

            return {
                "should_analyze": self.analyze_first_frame,
                "reason": "first_frame",
                "mean_difference": 0.0,
                "changed_ratio": 0.0,
            }

        previous = self._previous_frame

        if previous.shape != prepared.shape:
            previous = cv2.resize(
                previous,
                (
                    prepared.shape[1],
                    prepared.shape[0],
                ),
                interpolation=cv2.INTER_AREA,
            )

        difference = cv2.absdiff(
            previous,
            prepared,
        )

        mean_difference = float(
            np.mean(difference)
        )

        changed_ratio = float(
            np.mean(
                difference
                >= self.pixel_diff_threshold
            )
        )

        normal_change = (
            changed_ratio
            >= self.changed_ratio_threshold
            and mean_difference
            >= self.mean_diff_threshold
        )

        strong_change = (
            mean_difference
            >= self.strong_mean_diff_threshold
        )

        should_analyze = bool(
            normal_change or strong_change
        )

        if update_previous:
            self._previous_frame = (
                prepared.copy()
            )

        return {
            "should_analyze": should_analyze,
            "reason": (
                "frame_changed"
                if should_analyze
                else "no_significant_change"
            ),
            "mean_difference": round(
                mean_difference,
                3,
            ),
            "changed_ratio": round(
                changed_ratio,
                4,
            ),
        }

    def check_image(
        self,
        image_path,
        update_previous: bool = True,
    ):
        path = Path(image_path)

        frame = cv2.imread(str(path))

        if frame is None:
            raise ValueError(
                f"Could not read image: {path}"
            )

        return self.check_frame(
            frame,
            update_previous=update_previous,
        )

    def accept_frame(self, frame) -> None:
        prepared = self._prepare(frame)

        self._previous_frame = (
            prepared.copy()
        )

    def accept_image(self, image_path) -> None:
        path = Path(image_path)

        frame = cv2.imread(str(path))

        if frame is None:
            raise ValueError(
                f"Could not read image: {path}"
            )

        self.accept_frame(frame)

    def reset(self):
        self._previous_frame = None