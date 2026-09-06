from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.gift_analyzer import GiftAnalyzer
from core.history import HistoryDB


class FakeAIClient:
    def analyze_image(
        self,
        image_path,
        prompt,
    ):
        assert "detections" in prompt

        return """
        {
          "detections": [
            {
              "gift_id": "rose",
              "quantity": 2,
              "confidence": 0.93
            }
          ]
        }
        """


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        image_path = (
            tmp_path / "test_image.png"
        )

        image_path.write_bytes(
            b"fake-image"
        )

        db = HistoryDB.__new__(
            HistoryDB
        )

        db.db = str(
            tmp_path / "history.db"
        )

        db._create_table()

        analyzer = GiftAnalyzer(
            ROOT
            / "data"
            / "gifts"
            / "gift_catalog.json",
            min_confidence=0.80,
            history_db=db,
            ai_client=FakeAIClient(),
        )

        analyzer.catalog.data = {
            "gifts": [
                {
                    "id": "rose",
                    "name": "Rose",
                    "coins": 1,
                }
            ]
        }

        result = analyzer.analyze_image(
            image_path
        )

        with db._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    gift_id,
                    quantity,
                    total_coins,
                    confidence,
                    is_known,
                    image_path
                FROM gift_history
                """
            ).fetchone()

        assert result["total_coins"] == 2
        assert result["history_ids"] == [1]

        assert row[0] == "rose"
        assert row[1] == 2
        assert row[2] == 2
        assert row[3] == 0.93
        assert row[4] == 1
        assert row[5] is not None

    print(
        "Gift image pipeline test: PASS"
    )


if __name__ == "__main__":
    main()
