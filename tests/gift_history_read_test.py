from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.history import HistoryDB


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = HistoryDB.__new__(HistoryDB)
        db.db = str(
            Path(tmp) / "history.db"
        )

        db._create_table()

        db.save_gift(
            gift_id="rose",
            gift_name="Rose",
            quantity=3,
            coins_each=1,
            total_coins=3,
            confidence=0.95,
            is_known=True,
        )

        db.save_gift(
            gift_id="star",
            gift_name="Star",
            quantity=2,
            coins_each=100,
            total_coins=200,
            confidence=0.92,
            is_known=True,
        )

        db.save_gift(
            gift_id="unknown",
            gift_name=None,
            quantity=4,
            coins_each=None,
            total_coins=None,
            confidence=0.90,
            is_known=False,
        )

        rows = db.get_gift_history(
            limit=10
        )

        total = db.get_gift_total_coins()

        assert len(rows) == 3
        assert rows[0][2] == "unknown"
        assert rows[1][2] == "star"
        assert rows[2][2] == "rose"

        assert total == 203

    print(
        "Gift history read test: PASS"
    )


if __name__ == "__main__":
    main()
