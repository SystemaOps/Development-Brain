from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from agent_core.agent_platform.agents.base.contracts import ArtifactReference
from agent_core.domain.coding import CodingAttemptRequest, CodingAttemptResult
from agent_core.schemas import AcceptanceCriterionSpec


class AgentTaskTransitionContext(BaseModel):
    task_id: str
    objective: str
    acceptance_criteria: list[AcceptanceCriterionSpec] = Field(default_factory=list)
    input_artifacts: list[ArtifactReference] = Field(default_factory=list)
    planning_approved: bool = False
    prepared_coding_attempt: CodingAttemptRequest | None = None
    prepared_rework_attempt: CodingAttemptRequest | None = None
    latest_coding_attempt: CodingAttemptRequest | None = None
    latest_coding_result: CodingAttemptResult | None = None
    metadata: dict = Field(default_factory=dict)


@runtime_checkable
class AgentTransitionContextStore(Protocol):
    async def load_task_context(
        self,
        *,
        project_id: str,
        task_id: str,
        workflow_id: str,
        plan_version_id: str | None = None,
    ) -> AgentTaskTransitionContext | None: ...
