"""In-memory verification run repository reference implementation."""

from __future__ import annotations

from brain.domain.identity import ExecutionId, VerificationId
from brain.domain.verification_plan import VerificationRun


class InMemoryVerificationRunRepository:
    """In-memory storage for verification runs."""

    def __init__(self) -> None:
        self._runs: dict[VerificationId, VerificationRun] = {}

    async def save_run(self, run: VerificationRun) -> VerificationRun:
        self._runs[run.id] = run
        return run

    async def get_run(self, run_id: VerificationId) -> VerificationRun | None:
        return self._runs.get(run_id)

    async def list_runs_for_execution(self, execution_id: ExecutionId) -> list[VerificationRun]:
        return [r for r in self._runs.values() if r.execution_id == execution_id]

    async def delete_run(self, run_id: VerificationId) -> None:
        self._runs.pop(run_id, None)
