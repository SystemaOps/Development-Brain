"""Workflow orchestration states (Phase 28).

The orchestrator state is deliberately small and reference-oriented: ids only,
never whole repositories, source files, documents, capsules, or conversations
(Task 28.2).  Keys that nodes rewrite across steps use ``Annotated`` reducers
so LangGraph accepts one value per step.
"""

from __future__ import annotations

import uuid
from typing import Annotated, TypedDict

from brain.domain.workflow import WorkflowStage, WorkflowStatus


def _replace(old: object, new: object) -> object:
    del old
    return new


def _append_ids(accumulator: list[uuid.UUID], new: uuid.UUID) -> list[uuid.UUID]:
    if new not in accumulator:
        accumulator.append(new)
    return accumulator


class EngineeringState(TypedDict):
    """Canonical orchestrator state for the engineering workflow."""

    workflow_id: Annotated[uuid.UUID, _replace]
    project_id: Annotated[uuid.UUID, _replace]
    work_item_id: Annotated[uuid.UUID, _replace]
    repository_id: Annotated[uuid.UUID | None, _replace]
    base_revision: Annotated[str | None, _replace]
    context_capsule_id: Annotated[uuid.UUID | None, _replace]
    execution_id: Annotated[uuid.UUID | None, _replace]
    verification_id: Annotated[uuid.UUID | None, _replace]
    stage: Annotated[str, _replace]
    status: Annotated[str, _replace]
    retry_count: Annotated[int, _replace]
    waiting_for_human: Annotated[bool, _replace]
    correlation_id: Annotated[uuid.UUID, _replace]
    error: Annotated[str | None, _replace]
    observation_ids: Annotated[list[uuid.UUID], _append_ids]
    implementation_status: Annotated[str | None, _replace]
    modified_files: Annotated[list[str], _replace]


def initial_state(
    *,
    workflow_id: uuid.UUID,
    project_id: uuid.UUID,
    work_item_id: uuid.UUID,
    repository_id: uuid.UUID | None = None,
    base_revision: str | None = None,
    correlation_id: uuid.UUID | None = None,
) -> EngineeringState:
    return {
        "workflow_id": workflow_id,
        "project_id": project_id,
        "work_item_id": work_item_id,
        "repository_id": repository_id,
        "base_revision": base_revision,
        "context_capsule_id": None,
        "execution_id": None,
        "verification_id": None,
        "stage": WorkflowStage.INTAKE.value,
        "status": WorkflowStatus.RUNNING.value,
        "retry_count": 0,
        "waiting_for_human": False,
        "correlation_id": correlation_id or uuid.uuid4(),
        "error": None,
        "observation_ids": [],
        "implementation_status": None,
        "modified_files": [],
    }


__all__ = ["EngineeringState", "initial_state"]
