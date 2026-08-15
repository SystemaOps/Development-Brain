"""Planning ports (Phase 11).

``PlanRepository`` persists reconciled plans (items, assessments, evidence) so
the planning output is durable and can be re-evaluated.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.identity import PlanId, ProjectId
from brain.domain.planning import Plan


@runtime_checkable
class PlanRepository(Protocol):
    async def save_plan(self, plan: Plan) -> Plan: ...

    async def get_plan(self, plan_id: PlanId) -> Plan | None: ...

    async def list_plans_for_project(self, project_id: ProjectId) -> list[Plan]: ...

    async def delete_plan(self, plan_id: PlanId) -> None: ...


__all__ = ["PlanRepository"]
