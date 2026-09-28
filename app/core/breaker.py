import time
from typing import Literal

State = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    """Per-process circuit breaker for a remote dependency.

    closed: calls go through. After `failure_threshold` consecutive failures -> open.
    open: calls are skipped (caller degrades immediately) for `reset_seconds`.
    half_open: one trial call; success -> closed, failure -> open again.
    """

    def __init__(self, name: str, failure_threshold: int, reset_seconds: float) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.state: State = "closed"
        self.failures = 0
        self.opened_at = 0.0

    def allow(self) -> bool:
        if self.state == "open":
            if time.monotonic() - self.opened_at < self.reset_seconds:
                return False
            self.state = "half_open"
        return True

    def record_success(self) -> None:
        self.state = "closed"
        self.failures = 0

    def record_failure(self) -> None:
        self.failures += 1
        if self.state == "half_open" or self.failures >= self.failure_threshold:
            self.state = "open"
            self.opened_at = time.monotonic()
