from pathlib import Path

from PIL import Image, ImageStat


class BrightnessAnalyzer:
    """
    Deterministic brightness analysis for Livemetry Pulse.
    """

    @staticmethod
    def analyze(image_path: str) -> dict:
        path = Path(image_path)

        if not path.exists():
            raise FileNotFoundError(path)

        with Image.open(path) as image:
            gray = image.convert("L")

            mean = ImageStat.Stat(gray).mean[0]

            histogram = gray.histogram()
            total = sum(histogram)

            dark_ratio = (
                sum(histogram[:40]) / total * 100
            )

            bright_ratio = (
                sum(histogram[230:]) / total * 100
            )

        score = 20

        # Darkness
        if mean < 60 or dark_ratio >= 40:
            score -= 8
        elif mean < 80 or dark_ratio >= 32:
            score -= 5
        elif mean < 105 or dark_ratio >= 25:
            score -= 2

        # Excessive brightness / clipping
        if mean > 210 or bright_ratio >= 40:
            score -= 8
        elif mean > 190 or bright_ratio >= 25:
            score -= 5
        elif mean > 175 or bright_ratio >= 15:
            score -= 2

        score = max(0, min(20, score))

        return {
            "score": score,
            "mean": round(mean, 2),
            "dark_ratio": round(dark_ratio, 2),
            "bright_ratio": round(bright_ratio, 2),
        }
