import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )

from core.gift_stream_analyzer import GiftStreamAnalyzer


def test_combo_delta_calculation():
    with tempfile.TemporaryDirectory() as temp_dir:
        catalog_path = (
            Path(temp_dir)
            / "gift_catalog.json"
        )

        catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "updated_at": None,
                    "gifts": [
                        {
                            "id": "rose",
                            "name": "Rose",
                            "coins": 100,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        analyzer = GiftStreamAnalyzer(
            catalog_path=catalog_path,
            history_db=None,
            ai_client=object(),
        )

        quantities = [1, 2, 3]

        added_values = []
        coin_values = []

        for quantity in quantities:
            raw = f"""
            {{
              "detections": [
                {{
                  "gift_id": "rose",
                  "quantity": {quantity},
                  "sender_text": "user123",
                  "bbox": [0.08, 0.62, 0.38, 0.12],
                  "confidence": 0.95
                }}
              ]
            }}
            """

            result = analyzer.analyze_response(
                raw
            )

            added_values.append(
                sum(
                    item["quantity"]
                    for item
                    in result[
                        "counted_detections"
                    ]
                )
            )

            coin_values.append(
                result["total_coins"]
            )

        assert added_values == [
            1,
            1,
            1,
        ]

        assert coin_values == [
            100,
            100,
            100,
        ]

        assert sum(coin_values) == 300


if __name__ == "__main__":
    test_combo_delta_calculation()

    print(
        "PASS: GiftStreamAnalyzer combo delta calculation"
    )
