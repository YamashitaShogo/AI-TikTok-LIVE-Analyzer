import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.history import HistoryDB


class TempHistoryDB(HistoryDB):
    def __init__(self, db_path):
        self._test_db_path = Path(db_path)
        super().__init__()

    def _resolve_database_path(self):
        return self._test_db_path


def test_recent_summaries():
    with tempfile.TemporaryDirectory() as temp_dir:
        db = TempHistoryDB(
            Path(temp_dir) / "history.db"
        )

        for number in range(1, 16):
            db.save(
                score=number,
                prompt=f"prompt {number}",
                result=f"result {number}",
            )

        rows = db.get_recent_summaries(
            limit=10
        )

        assert len(rows) == 10

        assert [
            row[0]
            for row in rows
        ] == list(
            range(15, 5, -1)
        )

        assert all(
            len(row) == 3
            for row in rows
        )

        assert rows[0][2] == 15

        all_rows = db.get_all()

        assert len(all_rows) == 15


if __name__ == "__main__":
    test_recent_summaries()

    print(
        "PASS: lightweight history summaries"
    )
