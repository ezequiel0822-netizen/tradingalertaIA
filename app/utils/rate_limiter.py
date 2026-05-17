import time
from collections import deque


class RateLimiter:
    def __init__(self, max_calls: int, period_seconds: int) -> None:
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self.calls: deque[float] = deque()

    def wait(self) -> None:
        now = time.monotonic()
        while self.calls and now - self.calls[0] >= self.period_seconds:
            self.calls.popleft()

        if len(self.calls) >= self.max_calls:
            sleep_for = self.period_seconds - (now - self.calls[0])
            if sleep_for > 0:
                time.sleep(sleep_for)

        self.calls.append(time.monotonic())
