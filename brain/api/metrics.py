"""Metrics endpoint (Task 40.8).

Exposes the runtime metric snapshot as JSON and Prometheus text format.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from brain.api.auth import require_permission
from brain.api.dependencies import get_container
from brain.application.authorization import Permission
from brain.application.metrics import MetricSnapshot, MetricsService
from brain.bootstrap.container import BrainContainer

router = APIRouter()


@router.get("/api/v1/metrics")
async def metrics_json(
    request: Request,
    identity: Annotated[Any, Depends(require_permission(Permission.ADMIN))],
) -> MetricSnapshot:
    del identity
    container: BrainContainer = get_container(request)
    metrics = container.services["metrics"]
    assert isinstance(metrics, MetricsService)
    return metrics.snapshot()


@router.get("/metrics")
async def metrics_prometheus(
    request: Request,
    identity: Annotated[Any, Depends(require_permission(Permission.ADMIN))],
) -> str:
    del identity
    container: BrainContainer = get_container(request)
    metrics = container.services["metrics"]
    assert isinstance(metrics, MetricsService)
    snapshot = metrics.snapshot()
    lines: list[str] = []
    counters = snapshot.counters
    gauges = snapshot.gauges
    histograms = snapshot.histograms
    for name, counter_value in counters.items():
        lines.append(f"# TYPE {name} counter")
        lines.append(f"{name} {counter_value}")
    for name, gauge_value in gauges.items():
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {float(gauge_value)}")
    for name, hist in histograms.items():
        lines.append(f"# TYPE {name} histogram")
        buckets = hist["buckets"]
        counts = hist["counts"]
        assert isinstance(buckets, list) and isinstance(counts, list)
        for bound, count in zip(buckets, counts, strict=False):
            lines.append(f'{name}_bucket{{le="{bound}"}} {count}')
        lines.append(f"{name}_sum {hist['sum']}")
        lines.append(f"{name}_count {hist['total']}")
    return "\n".join(lines) + "\n"


__all__ = ["router"]
