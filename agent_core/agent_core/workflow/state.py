from __future__ import annotations

from typing import Any, TypedDict
from uuid import UUID


class PlanningGraphState(TypedDict, total=False):
    session_id: UUID

    project_id: UUID
    project_key: str
    original_request: str
    input_mode: str
    intake: dict[str, Any]

    current_intent: str
    selected_skill: str
    skill_confidence: float
    skill_results: list[dict[str, Any]]

    document_chunk_ids: list[UUID]
    chunk_summaries: list[dict[str, Any]]

    extracted_knowledge: dict[str, Any]

    ambiguity_status: str
    clarification_questions: list[dict[str, Any]]

    plan: dict[str, Any]
    plan_version_id: UUID

    context_capsule_ids: list[UUID]
    provisioning_job_ids: list[UUID]

    errors: list[str]