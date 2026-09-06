from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.gift_analyzer import GiftAnalyzer
from core.history import HistoryDB


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = HistoryDB.__new__(HistoryDB)
        db.db = str(
            Path(tmp) / "history.db"
        )
        db._create_table()

        analyzer = GiftAnalyzer(
            ROOT / "data" / "gifts" / "gift_catalog.json",
            min_confidence=0.80,
            history_db=db,
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

        result = analyzer.analyze_response(
            raw
        )

        with db._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    gift_id,
                    gift_name,
                    quantity,
                    coins_each,
                    total_coins,
                    confidence,
                    is_known
                FROM gift_history
                ORDER BY id
                """
            ).fetchall()

        assert result["history_ids"] == [1, 2]
        assert len(rows) == 2

        assert rows[0] == (
            "rose",
            "Rose",
            3,
            1,
            3,
            0.94,
            1,
        )

        assert rows[1] == (
            "unknown_gift",
            None,
            4,
            None,
            None,
            0.95,
            0,
        )

    print(
        "Gift history integration test: PASS"
    )


if __name__ == "__main__":
    main()
