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
    sys.path.insert(0, str(PROJECT_ROOT))

from core.gift_candidate_queue import GiftCandidateQueue
from core.gift_frame_gate import GiftFrameGate
from core.gift_monitor_controller import GiftMonitorController
from core.gift_monitor_worker import GiftMonitorWorker
from core.gift_obs_monitor import GiftOBSMonitor
from core.gift_rate_limiter import GiftRateLimiter
from core.gift_stream_analyzer import GiftStreamAnalyzer


class FakeOBS:
    def __init__(self):
        self.count = 0

    def is_connected(self):
        return True

    def get_current_scene(self):
        return "TestScene"

    def save_screenshot(self, scene, image_path):
        self.count += 1

        frame = np.zeros(
            (300, 300, 3),
            dtype=np.uint8,
        )

        if self.count >= 2:
            frame[50:250, 50:250] = 255

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

    def resolve_screenshot_path(self, image_path):
        return image_path


class SlowFakeAI:
    def __init__(self):
        self.started = threading.Event()
        self.finished = threading.Event()

    def analyze_image(self, image_path, prompt):
        self.started.set()
        time.sleep(2.0)
        self.finished.set()

        return """
        {
          "detections": []
        }
        """


def test_restart_waits_for_old_worker():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)

        catalog_path = temp_dir / "gift_catalog.json"

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

        obs = FakeOBS()
        ai = SlowFakeAI()

        candidate_queue = GiftCandidateQueue(
            directory=temp_dir / "pending",
            max_items=10,
        )

        controller = GiftMonitorController(
            stream_analyzer=GiftStreamAnalyzer(
                catalog_path=catalog_path,
                history_db=None,
                ai_client=ai,
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
            obs=obs,
            controller=controller,
            candidate_queue=candidate_queue,
        )

        worker = GiftMonitorWorker(
            monitor=monitor,
            capture_interval_seconds=0.2,
            capture_directory=temp_dir / "spool",
        )

        assert worker.start() is True

        assert ai.started.wait(
            timeout=3.0
        )

        worker.stop(
            wait=False
        )

        assert worker.start() is False

        assert ai.finished.wait(
            timeout=3.0
        )

        time.sleep(0.3)

        assert worker.start() is True

        worker.stop(
            wait=True,
            timeout=3.0,
        )


if __name__ == "__main__":
    test_restart_waits_for_old_worker()

    print(
        "PASS: gift monitor restart safety"
    )
