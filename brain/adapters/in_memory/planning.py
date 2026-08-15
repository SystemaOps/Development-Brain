"""In-memory plan repository reference implementation."""

from __future__ import annotations

from brain.domain.identity import PlanId, ProjectId
from brain.domain.planning import Plan


class InMemoryPlanRepository:
    """In-memory storage for reconciled plans."""

    def __init__(self) -> None:
        self._plans: dict[PlanId, Plan] = {}

    async def save_plan(self, plan: Plan) -> Plan:
        self._plans[plan.id] = plan
        return plan

    async def get_plan(self, plan_id: PlanId) -> Plan | None:
        return self._plans.get(plan_id)

    async def list_plans_for_project(self, project_id: ProjectId) -> list[Plan]:
        return [plan for plan in self._plans.values() if plan.project_id == project_id]

    async def delete_plan(self, plan_id: PlanId) -> None:
        self._plans.pop(plan_id, None)
