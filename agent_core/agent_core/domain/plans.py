from __future__ import annotations

from pydantic import BaseModel, Field

from agent_core.domain.enums import PlanNodeKind, PlanVersionStatus
from agent_core.domain.evidence import EvidenceRef


class AcceptanceCriterion(BaseModel):
    key: str
    statement: str
    verification_method: str
    mandatory: bool = True


class PlanNode(BaseModel):
    stable_key: str
    kind: PlanNodeKind
    title: str
    objective: str
    parent_stable_key: str | None = None
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class PlanVersion(BaseModel):
    project_key: str
    version_number: int
    status: PlanVersionStatus = PlanVersionStatus.DRAFT
    summary: str
    nodes: list[PlanNode] = Field(default_factory=list)
