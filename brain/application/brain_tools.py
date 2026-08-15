"""Brain tools for executors (Tasks 12.7, 12.8).

Task-scoped tools the coding executor can call (via Pi or any agent): resolve a
task, get symbol context, find related files/tests, fetch a requirement,
fetch decisions, and request more context.  Tool availability is enforced by
the executor's allowed-tool set (policy), so an executor only receives the
tools its permissions allow.
"""

from __future__ import annotations

from brain.application.jit_retrieval import JustInTimeRetrieval
from brain.domain.identity import (
    ProjectId,
    RepositoryId,
    RequirementId,
    WorkItemId,
)
from brain.domain.work_items import WorkItem
from brain.ports.repositories import WorkItemRepository

TOOL_REGISTRY = {
    "brain_get_task",
    "brain_get_symbol_context",
    "brain_find_related_files",
    "brain_find_related_tests",
    "brain_get_requirement",
    "brain_get_decisions",
    "brain_request_more_context",
}


class BrainTools:
    """Task-scoped tools exposed to executors."""

    def __init__(
        self,
        *,
        work_items: WorkItemRepository,
        jit: JustInTimeRetrieval,
    ) -> None:
        self._work_items = work_items
        self._jit = jit

    def allowed_tools(self, policy_tools: list[str] | None) -> list[str]:
        """Filter the executor's requested tools against policy (Task 12.8)."""
        if policy_tools is None:
            return sorted(TOOL_REGISTRY)
        return sorted(set(policy_tools) & TOOL_REGISTRY)

    async def brain_get_task(self, work_item_id: WorkItemId) -> WorkItem | None:
        return await self._work_items.get(work_item_id)

    async def brain_get_symbol_context(
        self,
        repository_id: RepositoryId,
        revision: str,
        qualified_name: str,
    ) -> dict[str, object] | None:
        candidate = await self._jit.get_symbol_context(repository_id, revision, qualified_name)
        if candidate is None:
            return None
        return {
            "entity_type": candidate.entity_type,
            "content": candidate.content,
            "reason": candidate.reason,
        }

    async def brain_find_related_files(
        self,
        repository_id: RepositoryId,
        revision: str,
        qualified_name: str,
    ) -> list[str]:
        return await self._jit.find_related_files(repository_id, revision, qualified_name)

    async def brain_find_related_tests(
        self,
        repository_id: RepositoryId,
        revision: str,
        qualified_name: str,
    ) -> list[str]:
        return await self._jit.find_related_tests(repository_id, revision, qualified_name)

    async def brain_get_requirement(
        self, requirement_id: RequirementId
    ) -> dict[str, object] | None:
        candidate = await self._jit.get_requirement(requirement_id)
        if candidate is None:
            return None
        return {"content": candidate.content, "reason": candidate.reason}

    async def brain_get_decisions(self, project_id: ProjectId) -> list[dict[str, object]]:
        return [
            {"content": c.content, "reason": c.reason}
            for c in await self._jit.get_decisions(project_id)
        ]

    async def brain_request_more_context(self, work_item_id: WorkItemId) -> list[dict[str, object]]:
        return [
            {"content": c.content, "reason": c.reason}
            for c in await self._jit.request_more_context(work_item_id)
        ]


__all__ = ["BrainTools", "TOOL_REGISTRY"]
