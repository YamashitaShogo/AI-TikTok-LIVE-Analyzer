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
from core.gift_obs_monitor import GiftOBSMonitor
from core.gift_stream_analyzer import GiftStreamAnalyzer


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


def test_obs_capture_gates_ai():
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

        base = np.zeros(
            (720, 1280, 3),
            dtype=np.uint8,
        )

        same = base.copy()

        changed = base.copy()
        changed[
            250:450,
            350:850,
        ] = 255

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
        )

        fake_obs = FakeOBS(
            frames=[
                base,
                same,
                changed,
            ],
            output_path=(
                temp_dir
                / "gift_monitor.png"
            ),
        )

        monitor = GiftOBSMonitor(
            obs=fake_obs,
            controller=controller,
        )

        first = monitor.poll_once()
        second = monitor.poll_once()
        third = monitor.poll_once()

        assert first["captured"] is True
        assert second["captured"] is True
        assert third["captured"] is True

        assert first[
            "result"
        ]["analyzed"] is False

        assert second[
            "result"
        ]["analyzed"] is False

        assert third[
            "result"
        ]["analyzed"] is True

        assert fake_ai.call_count == 1


if __name__ == "__main__":
    test_obs_capture_gates_ai()

    print(
        "PASS: GiftOBSMonitor captures and gates AI"
    )
