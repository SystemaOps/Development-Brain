"""Scheduler jobs (Phase 29).

Individual reconciliation jobs that the loop runs; each can also be invoked
directly (e.g. by tests or the CLI).
"""

from __future__ import annotations

from brain.scheduler.reconciliation import ReconciliationReport, ReconciliationService


async def run_repository_reconciliation(
    service: ReconciliationService,
) -> ReconciliationReport:
    report = ReconciliationReport()
    await service.reconcile_repositories(report)
    return report


async def run_stuck_execution_detection(
    service: ReconciliationService,
) -> ReconciliationReport:
    report = ReconciliationReport()
    await service.detect_stuck_executions(report)
    return report


async def run_projection_retry(
    service: ReconciliationService,
) -> ReconciliationReport:
    report = ReconciliationReport()
    await service.retry_failed_projections(report)
    return report


__all__ = [
    "run_projection_retry",
    "run_repository_reconciliation",
    "run_stuck_execution_detection",
]
