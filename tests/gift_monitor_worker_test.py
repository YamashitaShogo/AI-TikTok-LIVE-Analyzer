import json
import sys
import tempfile
import threading
import time
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
from core.gift_frame_gate import GiftFrameGate
from core.gift_monitor_controller import GiftMonitorController
from core.gift_monitor_worker import GiftMonitorWorker
from core.gift_obs_monitor import GiftOBSMonitor
from core.gift_rate_limiter import GiftRateLimiter
from core.gift_stream_analyzer import GiftStreamAnalyzer


class FakeOBS:
    def __init__(self):
        self.capture_count = 0
        self.lock = threading.Lock()

        self.base = np.zeros(
            (720, 1280, 3),
            dtype=np.uint8,
        )

        self.changed = self.base.copy()

        self.changed[
            250:450,
            350:850,
        ] = 255

    def is_connected(self):
        return True

    def get_current_scene(self):
        return "TestScene"

    def save_screenshot(
        self,
        scene,
        image_path,
    ):
        path = Path(image_path)

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.lock:
            self.capture_count += 1
            count = self.capture_count

        frame = (
            self.base
            if count == 1
            else self.changed
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

    def get_capture_count(self):
        with self.lock:
            return self.capture_count


class SlowFakeAIClient:
    def __init__(
        self,
        obs,
    ):
        self.obs = obs
        self.call_count = 0

        self.started = threading.Event()
        self.finished = threading.Event()

        self.captures_at_start = None
        self.captures_at_end = None

    def analyze_image(
        self,
        image_path,
        prompt,
    ):
        self.call_count += 1

        self.captures_at_start = (
            self.obs.get_capture_count()
        )

        self.started.set()

        time.sleep(3.0)

        self.captures_at_end = (
            self.obs.get_capture_count()
        )

        self.finished.set()

        return """
        {
          "detections": []
        }
        """


def test_capture_continues_during_ai():
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
                    "gifts": [],
                }
            ),
            encoding="utf-8",
        )

        fake_obs = FakeOBS()

        fake_ai = SlowFakeAIClient(
            fake_obs
        )

        candidate_queue = GiftCandidateQueue(
            directory=(
                temp_dir
                / "pending"
            ),
            max_items=30,
        )

        controller = GiftMonitorController(
            stream_analyzer=GiftStreamAnalyzer(
                catalog_path=catalog_path,
                history_db=None,
                ai_client=fake_ai,
            ),
            frame_gate=GiftFrameGate(
                analyze_first_frame=False,
            ),
            rate_limiter=GiftRateLimiter(
                max_calls=20,
                window_seconds=60.0,
            ),
        )

        monitor = GiftOBSMonitor(
            obs=fake_obs,
            controller=controller,
            candidate_queue=candidate_queue,
        )

        worker = GiftMonitorWorker(
            monitor=monitor,
            capture_interval_seconds=1.0,
            max_capture_backlog=30,
            capture_directory=(
                temp_dir
                / "capture_spool"
            ),
        )

        assert worker.start() is True

        try:
            assert fake_ai.started.wait(
                timeout=5.0
            )

            assert fake_ai.finished.wait(
                timeout=5.0
            )

            captures_during_ai = (
                fake_ai.captures_at_end
                - fake_ai.captures_at_start
            )

            assert captures_during_ai >= 2

        finally:
            worker.stop(
                wait=True,
                timeout=5.0,
            )


if __name__ == "__main__":
    test_capture_continues_during_ai()

    print(
        "PASS: gift monitor captures while AI is busy"
    )
