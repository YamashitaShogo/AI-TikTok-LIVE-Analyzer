import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )

from core.gift_event_tracker import GiftEventTracker


def make_detection(
    quantity,
    sender="user123",
    bbox=None,
):
    if bbox is None:
        bbox = [0.08, 0.62, 0.38, 0.12]

    return {
        "gift_id": "rose",
        "quantity": quantity,
        "sender_text": sender,
        "bbox": bbox,
    }


def test_combo_tracking():
    tracker = GiftEventTracker()

    frames = [
        [make_detection(1)],
        [make_detection(1)],
        [make_detection(2)],
        [make_detection(3)],
        [],
        [make_detection(1)],
    ]

    expected = [1, 0, 1, 1, 0, 1]
    actual = []

    for frame in frames:
        result = tracker.update(frame)

        actual.append(
            sum(
                item["added_quantity"]
                for item in result
            )
        )

    assert actual == expected
    assert sum(actual) == 4


def test_different_senders():
    tracker = GiftEventTracker()

    first = tracker.update([
        make_detection(
            1,
            sender="userA",
            bbox=[0.08, 0.55, 0.38, 0.10],
        ),
        make_detection(
            1,
            sender="userB",
            bbox=[0.08, 0.70, 0.38, 0.10],
        ),
    ])

    assert sum(
        item["added_quantity"]
        for item in first
    ) == 2

    second = tracker.update([
        make_detection(
            2,
            sender="userA",
            bbox=[0.08, 0.55, 0.38, 0.10],
        ),
        make_detection(
            1,
            sender="userB",
            bbox=[0.08, 0.70, 0.38, 0.10],
        ),
    ])

    assert sum(
        item["added_quantity"]
        for item in second
    ) == 1


def test_quantity_fluctuation():
    tracker = GiftEventTracker()

    quantities = [3, 2, 3, 4]
    actual = []

    for quantity in quantities:
        result = tracker.update([
            make_detection(quantity)
        ])

        actual.append(
            result[0]["added_quantity"]
        )

    assert actual == [3, 0, 0, 1]


if __name__ == "__main__":
    test_combo_tracking()
    print("PASS: combo tracking")

    test_different_senders()
    print("PASS: different senders")

    test_quantity_fluctuation()
    print("PASS: quantity fluctuation")

    print("ALL GIFT EVENT TRACKER TESTS PASSED")
