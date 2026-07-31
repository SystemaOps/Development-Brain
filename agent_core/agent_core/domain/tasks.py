from __future__ import annotations

from pydantic import BaseModel, Field

from agent_core.domain.evidence import EvidenceRef


class TaskAttempt(BaseModel):
    task_key: str
    attempt_number: int
    status: str
    changed_files: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
