"""Runtime metrics (Task 40.8).

Collects counters/gauges/histograms for: API latency, queue depth, workflow
duration, command failures, execution outcomes, verification pass/fail,
context token count, JIT retrieval requests, provider availability, and
observation projection success/failure.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class _Histogram:
    buckets: list[float]
    counts: list[int] = field(default_factory=list)
    total: int = 0
    sum: float = 0.0

    def __post_init__(self) -> None:
        if not self.counts:
            self.counts = [0] * len(self.buckets)

    def observe(self, value: float) -> None:
        self.sum += value
        self.total += 1
        for index, bound in enumerate(self.buckets):
            if value <= bound:
                self.counts[index] += 1
                break


@dataclass
class MetricSnapshot:
    counters: dict[str, int]
    gauges: dict[str, float]
    histograms: dict[str, dict[str, object]]


class MetricsService:
    """Thread-safe metric collection."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, _Histogram] = {}
        self._bucket_bounds = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]

    # -- counters ---------------------------------------------------------
    def inc(self, name: str, delta: int = 1, labels: str = "") -> None:
        key = f"{name}{{{labels}}}" if labels else name
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + delta

    def counter(self, name: str) -> int:
        return self._counters.get(name, 0)

    # -- gauges -----------------------------------------------------------
    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def gauge(self, name: str) -> float:
        return self._gauges.get(name, 0.0)

    # -- histograms -------------------------------------------------------
    def observe(self, name: str, value: float) -> None:
        with self._lock:
            hist = self._histograms.get(name)
            if hist is None:
                hist = _Histogram(buckets=list(self._bucket_bounds))
                self._histograms[name] = hist
            hist.observe(value)

    def histogram(self, name: str) -> tuple[list[float], list[int], int, float]:
        hist = self._histograms.get(name)
        if hist is None:
            return self._bucket_bounds, [0] * len(self._bucket_bounds), 0, 0.0
        return hist.buckets, hist.counts, hist.total, hist.sum

    # -- convenience ------------------------------------------------------
    def time(self, name: str) -> _Timer:
        return _Timer(self, name)

    def snapshot(self) -> MetricSnapshot:
        with self._lock:
            return MetricSnapshot(
                counters=dict(self._counters),
                gauges=dict(self._gauges),
                histograms={
                    name: {
                        "buckets": list(h.buckets),
                        "counts": list(h.counts),
                        "total": h.total,
                        "sum": h.sum,
                    }
                    for name, h in self._histograms.items()
                },
            )


class _Timer:
    def __init__(self, metrics: MetricsService, name: str) -> None:
        self._metrics = metrics
        self._name = name
        self._start = time.monotonic()

    def __enter__(self) -> _Timer:
        return self

    def __exit__(self, *args: object) -> None:
        self._metrics.observe(self._name, time.monotonic() - self._start)


__all__ = ["MetricsService"]
