import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )

from core.gift_stream_analyzer import GiftStreamAnalyzer
from core.history import HistoryDB


class TestHistoryDB(HistoryDB):
    def __init__(self, db_path):
        self._test_db_path = Path(db_path)
        super().__init__()

    def _resolve_database_path(self):
        self._test_db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        return self._test_db_path


def test_stream_history_delta():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)

        catalog_path = (
            temp_dir
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

        history = TestHistoryDB(
            temp_dir / "history.db"
        )

        analyzer = GiftStreamAnalyzer(
            catalog_path=catalog_path,
            history_db=history,
            ai_client=object(),
        )

        for quantity in [1, 2, 3]:
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

            analyzer.analyze_response(raw)

        with closing(
            sqlite3.connect(history.db)
        ) as conn:
            rows = conn.execute(
                """
                SELECT quantity, total_coins
                FROM gift_history
                ORDER BY id ASC
                """
            ).fetchall()

        assert rows == [
            (1, 100),
            (1, 100),
            (1, 100),
        ]

        assert sum(
            row[1]
            for row in rows
        ) == 300


if __name__ == "__main__":
    test_stream_history_delta()

    print(
        "PASS: GiftStreamAnalyzer stores delta quantities in DB"
    )
