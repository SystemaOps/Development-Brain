from __future__ import annotations

from pydantic import BaseModel, Field

from agent_core.domain.enums import VerificationOutcome
from agent_core.domain.evidence import EvidenceRef


class AcceptanceEvaluation(BaseModel):
    criterion_key: str
    outcome: VerificationOutcome
    rationale: str
    evidence: list[EvidenceRef] = Field(default_factory=list)


class VerificationResult(BaseModel):
    task_key: str
    outcome: VerificationOutcome
    evaluations: list[AcceptanceEvaluation] = Field(default_factory=list)
