"""In-memory per-IP token buckets (PLAN.md section 6). Single-process only."""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass


@dataclass
class Decision:
    allowed: bool
    limit: int
    remaining: int
    reset_s: int  # seconds until the bucket is full again
    retry_after_s: int  # seconds until the next token (0 if allowed)

    def headers(self) -> dict[str, str]:
        h = {"X-RateLimit-Limit": str(self.limit), "X-RateLimit-Remaining": str(self.remaining),
             "X-RateLimit-Reset": str(self.reset_s)}
        if not self.allowed:
            h["Retry-After"] = str(self.retry_after_s)
        return h


class TokenBucket:
    """`capacity` tokens per `window_s`, refilled continuously, one bucket per key."""

    def __init__(self, capacity: int, window_s: float, clock=time.monotonic, max_keys: int = 100_000):
        if capacity < 1 or window_s <= 0:
            raise ValueError("capacity must be >= 1 and window_s > 0")
        self.capacity, self.window_s, self.clock, self.max_keys = capacity, window_s, clock, max_keys
        self.rate = capacity / window_s
        self._b: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str) -> Decision:
        now = self.clock()
        with self._lock:
            tokens, last = self._b.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            allowed = tokens >= 1
            if allowed:
                tokens -= 1
            if len(self._b) >= self.max_keys and key not in self._b:
                self._prune(now)
            self._b[key] = (tokens, now)
        return Decision(allowed, self.capacity, int(tokens),
                        math.ceil((self.capacity - tokens) / self.rate),
                        0 if allowed else math.ceil((1 - tokens) / self.rate))

    def _prune(self, now: float) -> None:
        full = [k for k, (t, last) in self._b.items()
                if t + (now - last) * self.rate >= self.capacity]
        for k in full:
            del self._b[k]
