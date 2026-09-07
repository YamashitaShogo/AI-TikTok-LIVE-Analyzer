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

from core.gift_frame_gate import GiftFrameGate
from core.gift_monitor_controller import GiftMonitorController
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


def test_rate_limited_candidate_retained():
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

        base_path = temp_dir / "base.png"
        changed_path = temp_dir / "changed.png"

        base = np.zeros(
            (720, 1280, 3),
            dtype=np.uint8,
        )

        changed = base.copy()
        changed[
            250:450,
            350:850,
        ] = 255

        cv2.imwrite(
            str(base_path),
            base,
        )

        cv2.imwrite(
            str(changed_path),
            changed,
        )

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
                max_calls=5,
                window_seconds=60.0,
                clock=clock,
            ),
        )

        controller.process_image(
            base_path
        )

        paths = [
            changed_path,
            base_path,
            changed_path,
            base_path,
            changed_path,
        ]

        for path in paths:
            result = controller.process_image(
                path
            )

            assert result["analyzed"] is True

        assert fake_ai.call_count == 5

        blocked = controller.process_image(
            base_path
        )

        assert blocked["analyzed"] is False
        assert blocked[
            "blocked_by_rate_limit"
        ] is True

        assert fake_ai.call_count == 5

        blocked_again = (
            controller.process_image(
                base_path
            )
        )

        assert blocked_again[
            "blocked_by_rate_limit"
        ] is True

        assert fake_ai.call_count == 5

        clock.advance(60.0)

        retried = controller.process_image(
            base_path
        )

        assert retried["analyzed"] is True
        assert retried[
            "blocked_by_rate_limit"
        ] is False

        assert fake_ai.call_count == 6


if __name__ == "__main__":
    test_rate_limited_candidate_retained()

    print(
        "PASS: rate-limited gift candidate retained"
    )
