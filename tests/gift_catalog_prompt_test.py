from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.gift_analyzer import GiftAnalyzer


class FakeAIClient:
    def __init__(self):
        self.prompt = None

    def analyze_image(
        self,
        image_path,
        prompt,
    ):
        self.prompt = prompt

        return """
        {
          "detections": []
        }
        """


def main() -> None:
    fake_ai = FakeAIClient()

    analyzer = GiftAnalyzer(
        ROOT
        / "data"
        / "gifts"
        / "gift_catalog.json",
        ai_client=fake_ai,
    )

    analyzer.catalog.data = {
        "gifts": [
            {
                "id": "rose",
                "name": "Rose",
                "coins": 987654,
            }
        ]
    }

    result = analyzer.analyze_image(
        "dummy.png"
    )

    prompt = fake_ai.prompt

    assert prompt is not None

    assert (
        "- gift_id: rose | name: Rose"
        in prompt
    )

    assert "987654" not in prompt

    assert (
        result["detections"] == []
    )

    print(
        "Gift catalog prompt test: PASS"
    )


if __name__ == "__main__":
    main()
