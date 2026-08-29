"""Rate limiting for expensive operations (Task 40.5).

In-memory token-bucket limiters keyed by identity + operation.  Protected
operations: project analysis, context build, execution, verification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from brain.domain.identity_auth import Identity


@dataclass
class RateLimitRule:
    """``limit`` requests per ``window_seconds``."""

    limit: int
    window_seconds: int


DEFAULT_RULES: dict[str, RateLimitRule] = {
    "project_analysis": RateLimitRule(limit=10, window_seconds=60),
    "context_build": RateLimitRule(limit=20, window_seconds=60),
    "execution": RateLimitRule(limit=10, window_seconds=60),
    "verification": RateLimitRule(limit=10, window_seconds=60),
}


class RateLimitExceeded(Exception):
    """Raised when a caller exceeds the configured rate."""


class RateLimiter:
    """Sliding-window token bucket per (identity, operation)."""

    def __init__(self, rules: dict[str, RateLimitRule] | None = None) -> None:
        self._rules = rules or dict(DEFAULT_RULES)
        self._buckets: dict[tuple[str, str], list[float]] = {}

    def check(self, identity: Identity, operation: str) -> None:
        rule = self._rules.get(operation)
        if rule is None:
            return
        now = time.monotonic()
        key = (identity.name, operation)
        window_start = now - rule.window_seconds
        hits = [t for t in self._buckets.get(key, []) if t > window_start]
        if len(hits) >= rule.limit:
            raise RateLimitExceeded(
                f"rate limit exceeded for '{operation}' ({rule.limit}/{rule.window_seconds}s)"
            )
        hits.append(now)
        self._buckets[key] = hits

    def count(self, identity: Identity, operation: str) -> int:
        return len(self._buckets.get((identity.name, operation), []))


__all__ = ["RateLimitExceeded", "RateLimitRule", "RateLimiter"]
