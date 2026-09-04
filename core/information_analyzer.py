from pathlib import Path

import cv2


class InformationAnalyzer:
    """
    Deterministic screen-density analysis for Livemetry Pulse.

    Measures small and medium visual elements without double counting.
    Thresholds are provisional and must be calibrated with more samples.
    """

    @staticmethod
    def analyze(image_path: str) -> dict:
        path = Path(image_path)

        if not path.exists():
            raise FileNotFoundError(path)

        image = cv2.imread(str(path))

        if image is None:
            raise ValueError(f"Could not load image: {path}")

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY,
        )

        gray = cv2.resize(
            gray,
            (720, 1280),
            interpolation=cv2.INTER_AREA,
        )

        binary = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            21,
            7,
        )

        contours, _ = cv2.findContours(
            binary,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        small_elements = 0
        medium_elements = 0

        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h

            # Small UI / text-like element
            if (
                8 <= w <= 120
                and 5 <= h <= 60
                and area < 3000
            ):
                small_elements += 1

            # Medium UI block
            elif (
                20 <= w <= 250
                and 10 <= h <= 120
                and area >= 300
            ):
                medium_elements += 1

        element_count = (
            small_elements
            + medium_elements
        )

        # Provisional score.
        # We will calibrate these thresholds with more test images.
        if element_count >= 350:
            score = 11
        elif element_count >= 300:
            score = 13
        else:
            score = 15

        return {
            "score": score,
            "small_elements": small_elements,
            "medium_elements": medium_elements,
            "element_count": element_count,
        }
