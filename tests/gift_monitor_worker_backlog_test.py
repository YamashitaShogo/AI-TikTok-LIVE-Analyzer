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
from core.gift_monitor_worker import GiftMonitorWorker


class FakeOBS:
    def __init__(self):
        self.count = 0

    def is_connected(self):
        return True

    def get_current_scene(self):
        return "TestScene"

    def save_screenshot(
        self,
        scene,
        image_path,
    ):
        self.count += 1

        frame = np.full(
            (100, 100, 3),
            self.count * 40,
            dtype=np.uint8,
        )

        path = Path(image_path)

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        return bool(
            cv2.imwrite(
                str(path),
                frame,
            )
        )

    def resolve_screenshot_path(
        self,
        image_path,
    ):
        return image_path


class FakeController:
    pass


class FakeMonitor:
    def __init__(
        self,
        obs,
        candidate_queue,
    ):
        self.obs = obs
        self.controller = FakeController()
        self.candidate_queue = candidate_queue


def test_capture_backlog_is_bounded():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)

        obs = FakeOBS()

        candidate_queue = GiftCandidateQueue(
            directory=(
                temp_dir
                / "pending"
            ),
            max_items=10,
        )

        monitor = FakeMonitor(
            obs=obs,
            candidate_queue=candidate_queue,
        )

        worker = GiftMonitorWorker(
            monitor=monitor,
            max_capture_backlog=2,
            capture_directory=(
                temp_dir
                / "spool"
            ),
        )

        worker._capture_once()
        worker._capture_once()

        first_paths = list(
            worker._capture_queue.queue
        )

        assert len(first_paths) == 2

        oldest_path = first_paths[0]

        assert oldest_path.exists()

        worker._capture_once()

        remaining_paths = list(
            worker._capture_queue.queue
        )

        assert worker.capture_backlog_count == 2
        assert oldest_path not in remaining_paths
        assert not oldest_path.exists()

        events = []

        while True:
            event = worker.get_event_nowait()

            if event is None:
                break

            events.append(event)

        overflow_events = [
            event
            for event in events
            if event["type"]
            == "capture_backlog_overflow"
        ]

        assert len(overflow_events) == 1
        assert overflow_events[0][
            "backlog"
        ] == 2


if __name__ == "__main__":
    test_capture_backlog_is_bounded()

    print(
        "PASS: gift monitor backlog stays bounded"
    )
