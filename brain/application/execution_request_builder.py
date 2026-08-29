"""ExecutionRequest builder (Task 12.4).

Builds a canonical :class:`ExecutionRequest` from the WorkItem, its context
capsule, the repository, an isolated workspace, the policy permissions, and
the chosen executor.
"""

from __future__ import annotations

from dataclasses import dataclass

from brain.application.workspace_manager import Workspace
from brain.domain.context import ContextCapsule
from brain.domain.executions import ExecutionPermissions, ExecutionRequest
from brain.domain.executor import ExecutorDescriptor
from brain.domain.identity import (
    ActorId,
    ExecutionId,
    WorkflowId,
    new_execution_id,
    new_workflow_id,
)
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.work_items import WorkItem


@dataclass
class BuiltExecution:
    request: ExecutionRequest
    execution_id: ExecutionId


class ExecutionRequestBuilder:
    """Assemble an :class:`ExecutionRequest` for any executor."""

    async def build(
        self,
        *,
        project: Project,
        work_item: WorkItem,
        repository: Repository,
        workspace: Workspace,
        executor: ExecutorDescriptor,
        context_capsule: ContextCapsule | None = None,
        workflow_id: WorkflowId | None = None,
        permissions: ExecutionPermissions | None = None,
        executor_id: ActorId | None = None,
    ) -> BuiltExecution:
        del project
        execution_id = new_execution_id()
        request = ExecutionRequest(
            execution_id=execution_id,
            workflow_id=workflow_id or new_workflow_id(),
            work_item_id=work_item.id,
            repository_ref=repository.clone_url or repository.name,
            base_revision=workspace.base_revision,
            context_capsule_id=context_capsule.id if context_capsule else None,
            permissions=permissions or _permissions_for(executor),
            correlation_id=execution_id,
        )
        return BuiltExecution(request=request, execution_id=execution_id)


def _permissions_for(executor: ExecutorDescriptor) -> ExecutionPermissions:
    """Derive the executor's permission set from its capabilities/metadata."""
    # Defaults are conservative (read-only, no shell).  An executor that
    # supports tooling may gain write/commit rights via its metadata policy.
    return ExecutionPermissions(
        repository_read=True,
        repository_write=bool(executor.metadata.get("repository_write", False)),
        shell=bool(executor.metadata.get("shell", False)),
        network=bool(executor.metadata.get("network", False)),
        git_commit=bool(executor.metadata.get("git_commit", False)),
        git_push=bool(executor.metadata.get("git_push", False)),
    )


def _default_workflow_id() -> WorkflowId:
    return new_workflow_id()


__all__ = ["BuiltExecution", "ExecutionRequestBuilder"]
