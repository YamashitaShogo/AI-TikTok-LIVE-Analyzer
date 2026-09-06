from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.gift_analyzer import GiftAnalyzer


def main() -> None:
    analyzer = GiftAnalyzer(
        ROOT / "data" / "gifts" / "gift_catalog.json",
        min_confidence=0.80,
    )

    analyzer.catalog.data = {
        "gifts": [
            {
                "id": "rose",
                "name": "Rose",
                "coins": 1,
            },
            {
                "id": "star",
                "name": "Star",
                "coins": 100,
            },
        ]
    }

    raw = """
    {
      "detections": [
        {
          "gift_id": "rose",
          "quantity": 3,
          "confidence": 0.94
        },
        {
          "gift_id": "star",
          "quantity": 2,
          "confidence": 0.50
        },
        {
          "gift_id": "unknown_gift",
          "quantity": 4,
          "confidence": 0.95
        }
      ]
    }
    """

    result = analyzer.analyze_response(raw)

    assert result["total_coins"] == 3
    assert len(result["accepted_detections"]) == 2
    assert len(result["ignored_detections"]) == 1
    assert result["unknown_count"] == 1

    empty_result = analyzer.analyze_response(
        '{"detections":[]}'
    )

    assert empty_result["total_coins"] == 0
    assert empty_result["unknown_count"] == 0

    print("Gift pipeline smoke test: PASS")


if __name__ == "__main__":
    main()
