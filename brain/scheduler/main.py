"""Scheduler entry point (Phase 29).

Runs the reconciliation loop on an interval using the same ``BrainContainer``
as the API and worker.  Graceful shutdown stops the loop and closes the
container.
"""

from __future__ import annotations

import asyncio
import logging

from brain.bootstrap.container import BrainContainer, create_brain_container
from brain.bootstrap.settings import BrainSettings
from brain.scheduler.reconciliation import ReconciliationService

logger = logging.getLogger("brain.scheduler")


class SchedulerLoop:
    """Periodically runs reconciliation until stopped."""

    def __init__(
        self,
        *,
        container: BrainContainer,
        interval_seconds: float = 60.0,
        stuck_threshold_seconds: int = 3600,
    ) -> None:
        self._service = ReconciliationService(
            container,
            stuck_threshold_seconds=stuck_threshold_seconds,
        )
        self._interval = interval_seconds
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    async def run_once(self) -> None:
        report = await self._service.reconcile()
        logger.info(
            "reconciled: repos=%d stale=%d synced=%d stuck=%d recovered=%d projections_retried=%d",
            report.repositories_checked,
            report.repositories_stale,
            report.repositories_synced,
            report.stuck_executions,
            report.stuck_recovered,
            report.projections_retried,
        )

    async def run(self, *, iterations: int | None = None) -> int:
        """Run the reconciliation loop until stopped or iterations exhausted."""
        ran = 0
        while not self._stop and (iterations is None or ran < iterations):
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("reconciliation pass failed")
            ran += 1
            if self._stop or (iterations is not None and ran >= iterations):
                break
            await asyncio.sleep(self._interval)
        return ran


async def run_scheduler_async(
    *,
    interval_seconds: float = 60.0,
    iterations: int | None = None,
) -> int:
    settings = BrainSettings()
    container: BrainContainer = await create_brain_container(settings)
    loop = SchedulerLoop(container=container, interval_seconds=interval_seconds)
    try:
        return await loop.run(iterations=iterations)
    finally:
        await container.close()


def main() -> None:
    """Console entry point (registered as ``brain-scheduler`` in Phase 31)."""
    logging.basicConfig(level=logging.INFO)
    code = asyncio.run(run_scheduler_async())
    raise SystemExit(code)


if __name__ == "__main__":
    main()
