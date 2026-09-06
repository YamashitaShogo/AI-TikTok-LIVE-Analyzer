import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )

from core.gift_frame_gate import GiftFrameGate


def test_unchanged_and_changed_frames():
    gate = GiftFrameGate(
        roi=None,
        analyze_first_frame=False,
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

    first = gate.check_frame(base)
    same_result = gate.check_frame(same)
    changed_result = gate.check_frame(changed)

    assert first["should_analyze"] is False
    assert same_result["should_analyze"] is False
    assert changed_result["should_analyze"] is True


def test_roi_filtering():
    gate = GiftFrameGate(
        roi=(0.25, 0.25, 0.50, 0.50),
        analyze_first_frame=False,
    )

    base = np.zeros(
        (720, 1280, 3),
        dtype=np.uint8,
    )

    outside_change = base.copy()
    outside_change[
        0:100,
        0:200,
    ] = 255

    inside_change = base.copy()
    inside_change[
        250:450,
        450:850,
    ] = 255

    first = gate.check_frame(base)
    outside = gate.check_frame(outside_change)
    reset_base = gate.check_frame(base)
    inside = gate.check_frame(inside_change)

    assert first["should_analyze"] is False
    assert outside["should_analyze"] is False
    assert reset_base["should_analyze"] is False
    assert inside["should_analyze"] is True


if __name__ == "__main__":
    test_unchanged_and_changed_frames()
    print("PASS: frame change detection")

    test_roi_filtering()
    print("PASS: ROI filtering")

    print("ALL GIFT FRAME GATE TESTS PASSED")
