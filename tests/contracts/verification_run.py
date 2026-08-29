"""VerificationRunRepository contract."""

from __future__ import annotations

import pytest

from brain.domain.identity import new_execution_id, new_work_item_id
from brain.domain.verification_plan import (
    VerificationPlan,
    VerificationRun,
    VerificationVerdict,
)
from brain.ports.verification import VerificationRunRepository


def _run() -> VerificationRun:
    execution_id = new_execution_id()
    plan = VerificationPlan(execution_id=execution_id, work_item_id=new_work_item_id())
    return VerificationRun(
        execution_id=execution_id,
        plan=plan,
        verdict=VerificationVerdict.PASS,
        pr_allowed=True,
    )


class VerificationRunRepositoryContract:
    @pytest.fixture
    def verification_runs(self) -> VerificationRunRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, verification_runs: VerificationRunRepository) -> None:
        assert isinstance(verification_runs, VerificationRunRepository)

    async def test_save_and_get_round_trip(
        self, verification_runs: VerificationRunRepository
    ) -> None:
        run = _run()
        await verification_runs.save_run(run)
        stored = await verification_runs.get_run(run.id)
        assert stored is not None
        assert stored.id == run.id
        assert stored.pr_allowed is True

    async def test_list_by_execution(self, verification_runs: VerificationRunRepository) -> None:
        run = _run()
        await verification_runs.save_run(run)
        runs = await verification_runs.list_runs_for_execution(run.execution_id)
        assert [r.id for r in runs] == [run.id]

    async def test_delete(self, verification_runs: VerificationRunRepository) -> None:
        run = _run()
        await verification_runs.save_run(run)
        await verification_runs.delete_run(run.id)
        assert await verification_runs.get_run(run.id) is None

    async def test_missing_run_returns_none(
        self, verification_runs: VerificationRunRepository
    ) -> None:
        assert await verification_runs.get_run(_run().id) is None
