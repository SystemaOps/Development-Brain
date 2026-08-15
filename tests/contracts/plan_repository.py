"""PlanRepository contract."""

from __future__ import annotations

import pytest

from brain.domain.identity import new_project_id
from brain.domain.planning import Plan, PlanItem, PlanItemType
from brain.ports.planning import PlanRepository


def _plan() -> Plan:
    project_id = new_project_id()
    return Plan(
        project_id=project_id,
        title="Auth plan",
        items=[
            PlanItem(
                project_id=project_id,
                item_type=PlanItemType.TASK,
                title="Implement login",
                acceptance_criteria=["login works"],
            )
        ],
    )


class PlanRepositoryContract:
    @pytest.fixture
    def plan_repository(self) -> PlanRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, plan_repository: PlanRepository) -> None:
        assert isinstance(plan_repository, PlanRepository)

    async def test_save_and_get_round_trip(self, plan_repository: PlanRepository) -> None:
        plan = _plan()
        await plan_repository.save_plan(plan)
        stored = await plan_repository.get_plan(plan.id)
        assert stored is not None
        assert stored.id == plan.id
        assert stored.title == "Auth plan"
        assert len(stored.items) == 1
        assert stored.items[0].title == "Implement login"

    async def test_list_by_project(self, plan_repository: PlanRepository) -> None:
        plan = _plan()
        await plan_repository.save_plan(plan)
        plans = await plan_repository.list_plans_for_project(plan.project_id)
        assert [p.id for p in plans] == [plan.id]

    async def test_delete(self, plan_repository: PlanRepository) -> None:
        plan = _plan()
        await plan_repository.save_plan(plan)
        await plan_repository.delete_plan(plan.id)
        assert await plan_repository.get_plan(plan.id) is None

    async def test_missing_plan_returns_none(self, plan_repository: PlanRepository) -> None:
        assert await plan_repository.get_plan(_plan().id) is None
