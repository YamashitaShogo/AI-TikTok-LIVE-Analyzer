import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )

from core.gift_rate_limiter import GiftRateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_rate_limit():
    clock = FakeClock()

    limiter = GiftRateLimiter(
        max_calls=5,
        window_seconds=60.0,
        clock=clock,
    )

    assert limiter.remaining_calls() == 5

    for _ in range(5):
        assert limiter.can_call() is True
        limiter.record_call()

    assert limiter.can_call() is False
    assert limiter.remaining_calls() == 0
    assert limiter.seconds_until_available() == 60.0

    try:
        limiter.record_call()
        raise AssertionError(
            "6th call should be blocked"
        )
    except RuntimeError:
        pass

    clock.advance(59.0)

    assert limiter.can_call() is False
    assert limiter.seconds_until_available() == 1.0

    clock.advance(1.0)

    assert limiter.can_call() is True
    assert limiter.remaining_calls() == 5

    limiter.record_call()

    assert limiter.remaining_calls() == 4


if __name__ == "__main__":
    test_rate_limit()

    print(
        "PASS: GiftRateLimiter rolling window"
    )
