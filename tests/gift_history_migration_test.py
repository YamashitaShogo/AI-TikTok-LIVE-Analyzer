import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )

from core.history import HistoryDB


class TestHistoryDB(HistoryDB):
    def __init__(self, db_path):
        self._test_db_path = Path(db_path)
        super().__init__()

    def _resolve_database_path(self):
        return self._test_db_path


def test_gift_history_migration():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = (
            Path(temp_dir)
            / "history.db"
        )

        conn = sqlite3.connect(db_path)

        conn.execute(
            """
            CREATE TABLE gift_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                gift_id TEXT NOT NULL,
                gift_name TEXT,
                quantity INTEGER NOT NULL,
                coins_each INTEGER,
                total_coins INTEGER,
                confidence REAL,
                is_known INTEGER NOT NULL DEFAULT 1,
                image_path TEXT
            )
            """
        )

        conn.commit()
        conn.close()

        history = TestHistoryDB(
            db_path
        )

        conn = sqlite3.connect(
            history.db
        )

        columns = [
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(gift_history)"
            ).fetchall()
        ]

        conn.close()

        assert "sender_text" in columns
        assert "bbox_json" in columns


if __name__ == "__main__":
    test_gift_history_migration()

    print(
        "PASS: gift_history schema migration"
    )
