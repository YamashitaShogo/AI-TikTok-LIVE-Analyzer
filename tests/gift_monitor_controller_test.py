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


def test_ai_called_only_for_changed_frame():
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
        same_path = temp_dir / "same.png"
        changed_path = (
            temp_dir
            / "changed.png"
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

        cv2.imwrite(
            str(base_path),
            base,
        )

        cv2.imwrite(
            str(same_path),
            same,
        )

        cv2.imwrite(
            str(changed_path),
            changed,
        )

        fake_ai = FakeAIClient()

        stream_analyzer = (
            GiftStreamAnalyzer(
                catalog_path=catalog_path,
                history_db=None,
                ai_client=fake_ai,
            )
        )

        controller = GiftMonitorController(
            stream_analyzer=stream_analyzer,
            frame_gate=GiftFrameGate(
                analyze_first_frame=False,
            ),
        )

        first = controller.process_image(
            base_path
        )

        same_result = (
            controller.process_image(
                same_path
            )
        )

        changed_result = (
            controller.process_image(
                changed_path
            )
        )

        assert first["analyzed"] is False
        assert same_result["analyzed"] is False
        assert changed_result["analyzed"] is True

        assert fake_ai.call_count == 1


if __name__ == "__main__":
    test_ai_called_only_for_changed_frame()

    print(
        "PASS: GiftMonitorController gates AI calls"
    )
