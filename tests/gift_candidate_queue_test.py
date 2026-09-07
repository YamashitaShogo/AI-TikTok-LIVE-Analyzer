import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )

from core.gift_candidate_queue import GiftCandidateQueue


def test_candidate_queue():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)

        source_path = (
            temp_dir
            / "gift_monitor.png"
        )

        queue_dir = (
            temp_dir
            / "pending"
        )

        queue = GiftCandidateQueue(
            directory=queue_dir,
            max_items=2,
        )

        frame_a = np.zeros(
            (300, 300, 3),
            dtype=np.uint8,
        )

        frame_a[
            50:150,
            50:150,
        ] = 255

        cv2.imwrite(
            str(source_path),
            frame_a,
        )

        first = queue.enqueue(
            source_path
        )

        assert first["queued"] is True
        assert len(queue) == 1

        saved_a = Path(
            first["path"]
        )

        assert saved_a.exists()

        duplicate = queue.enqueue(
            source_path
        )

        assert duplicate["queued"] is False
        assert duplicate["reason"] == "duplicate"
        assert len(queue) == 1

        frame_b = np.zeros(
            (300, 300, 3),
            dtype=np.uint8,
        )

        frame_b[
            150:250,
            150:250,
        ] = 255

        cv2.imwrite(
            str(source_path),
            frame_b,
        )

        stored_a = cv2.imread(
            str(saved_a)
        )

        assert stored_a is not None
        assert np.array_equal(
            stored_a,
            frame_a,
        )

        second = queue.enqueue(
            source_path
        )

        assert second["queued"] is True
        assert len(queue) == 2

        frame_c = np.full(
            (300, 300, 3),
            127,
            dtype=np.uint8,
        )

        cv2.imwrite(
            str(source_path),
            frame_c,
        )

        full = queue.enqueue(
            source_path
        )

        assert full["queued"] is False
        assert full["reason"] == "queue_full"
        assert len(queue) == 2

        assert queue.peek() == saved_a

        acknowledged = (
            queue.acknowledge()
        )

        assert acknowledged == saved_a
        assert not saved_a.exists()
        assert len(queue) == 1

        queue.clear()

        assert len(queue) == 0
        assert list(
            queue_dir.iterdir()
        ) == []


if __name__ == "__main__":
    test_candidate_queue()

    print(
        "PASS: gift candidate queue"
    )
