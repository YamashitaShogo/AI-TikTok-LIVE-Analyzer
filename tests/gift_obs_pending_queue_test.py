import json
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
from core.gift_frame_gate import GiftFrameGate
from core.gift_monitor_controller import GiftMonitorController
from core.gift_obs_monitor import GiftOBSMonitor
from core.gift_rate_limiter import GiftRateLimiter
from core.gift_stream_analyzer import GiftStreamAnalyzer


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeAIClient:
    def __init__(self):
        self.call_count = 0

    def analyze_image(
        self,
        image_path,
        prompt,
    ):
        self.call_count += 1

        return """
        {
          "detections": []
        }
        """


class FakeOBS:
    def __init__(
        self,
        frames,
        output_path,
    ):
        self.frames = frames
        self.output_path = Path(
            output_path
        )
        self.index = 0

    def is_connected(self):
        return True

    def get_current_scene(self):
        return "TestScene"

    def save_screenshot(
        self,
        scene,
        image_path,
    ):
        if self.index >= len(
            self.frames
        ):
            return False

        frame = self.frames[
            self.index
        ]

        self.index += 1

        self.output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        return bool(
            cv2.imwrite(
                str(self.output_path),
                frame,
            )
        )

    def resolve_screenshot_path(
        self,
        image_path,
    ):
        return self.output_path


def test_pending_candidate_survives_overwrite():
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

        live_path = (
            temp_dir
            / "gift_monitor.png"
        )

        queue = GiftCandidateQueue(
            directory=(
                temp_dir
                / "pending"
            ),
            max_items=10,
        )

        frame_a = np.zeros(
            (720, 1280, 3),
            dtype=np.uint8,
        )

        frame_b = frame_a.copy()
        frame_b[
            100:300,
            150:650,
        ] = 255

        frame_c = frame_a.copy()
        frame_c[
            400:600,
            650:1150,
        ] = 255

        clock = FakeClock()
        fake_ai = FakeAIClient()

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
                max_calls=1,
                window_seconds=60.0,
                clock=clock,
            ),
        )

        obs = FakeOBS(
            frames=[
                frame_a,
                frame_b,
                frame_c,
                frame_b,
            ],
            output_path=live_path,
        )

        monitor = GiftOBSMonitor(
            obs=obs,
            controller=controller,
            candidate_queue=queue,
        )

        baseline = monitor.poll_once()
        first_change = monitor.poll_once()
        blocked = monitor.poll_once()

        assert baseline[
            "result"
        ]["analyzed"] is False

        assert first_change[
            "result"
        ]["analyzed"] is True

        assert blocked[
            "result"
        ]["blocked_by_rate_limit"] is True

        assert blocked[
            "queue"
        ]["queued"] is True

        assert fake_ai.call_count == 1
        assert len(queue) == 1

        pending_path = queue.peek()

        assert pending_path is not None
        assert pending_path.exists()

        saved_candidate = cv2.imread(
            str(pending_path)
        )

        assert saved_candidate is not None

        assert np.array_equal(
            saved_candidate,
            frame_c,
        )

        # OBSのライブ画像を別フレームで上書き
        monitor.poll_once()

        current_live = cv2.imread(
            str(live_path)
        )

        assert current_live is not None

        assert np.array_equal(
            current_live,
            frame_b,
        )

        # 保存候補Cは消えていない
        assert len(queue) == 1
        assert pending_path.exists()

        saved_after_overwrite = cv2.imread(
            str(pending_path)
        )

        assert saved_after_overwrite is not None

        assert np.array_equal(
            saved_after_overwrite,
            frame_c,
        )

        # レート制限解除
        clock.advance(60.0)

        retried = (
            monitor.retry_pending_once()
        )

        assert retried["processed"] is True
        assert retried["reason"] == "analyzed"

        assert fake_ai.call_count == 2
        assert len(queue) == 0
        assert not pending_path.exists()


if __name__ == "__main__":
    test_pending_candidate_survives_overwrite()

    print(
        "PASS: pending OBS candidate survives overwrite"
    )
