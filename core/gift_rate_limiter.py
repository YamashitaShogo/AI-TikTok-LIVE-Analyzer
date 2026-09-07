import time
from collections import deque
from typing import Callable


class GiftRateLimiter:
    """
    Rolling-window rate limiter for gift AI analysis.
    """

    def __init__(
        self,
        max_calls: int = 5,
        window_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ):
        self.max_calls = max(
            1,
            int(max_calls),
        )

        self.window_seconds = max(
            0.1,
            float(window_seconds),
        )

        self._clock = (
            clock
            if clock is not None
            else time.monotonic
        )

        self._calls = deque()

    def _cleanup(self) -> float:
        now = self._clock()

        while (
            self._calls
            and now - self._calls[0]
            >= self.window_seconds
        ):
            self._calls.popleft()

        return now

    def can_call(self) -> bool:
        self._cleanup()

        return (
            len(self._calls)
            < self.max_calls
        )

    def record_call(self) -> None:
        now = self._cleanup()

        if len(self._calls) >= self.max_calls:
            raise RuntimeError(
                "Gift AI rate limit exceeded."
            )

        self._calls.append(now)

    def seconds_until_available(self) -> float:
        now = self._cleanup()

        if len(self._calls) < self.max_calls:
            return 0.0

        remaining = (
            self.window_seconds
            - (now - self._calls[0])
        )

        return max(
            0.0,
            remaining,
        )

    def remaining_calls(self) -> int:
        self._cleanup()

        return max(
            0,
            self.max_calls - len(self._calls),
        )

    def reset(self) -> None:
        self._calls.clear()