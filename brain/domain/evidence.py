"""Evidence domain.

Evidence carries deterministic, machine-readable proof (test results, diffs,
build output, lint output, runtime observations) rather than a bare
natural-language claim.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import (
    ArtifactId,
    EvidenceId,
    ExecutionId,
    new_evidence_id,
)


class EvidenceType(StrEnum):
    TEST_RESULT = "test_result"
    GIT_DIFF = "git_diff"
    BUILD_OUTPUT = "build_output"
    LINT_RESULT = "lint_result"
    STATIC_ANALYSIS = "static_analysis"
    VERIFICATION_REPORT = "verification_report"
    RUNTIME_OBSERVATION = "runtime_observation"
    COMMAND_OUTPUT = "command_output"
    OBSERVATION = "observation"
    BLOCKER = "blocker"
    TRACE = "trace"


class Evidence(BaseModel):
    id: EvidenceId = Field(default_factory=new_evidence_id)
    execution_id: ExecutionId
    evidence_type: EvidenceType
    source: str
    artifact_id: ArtifactId | None = None
    payload: dict[str, object] = Field(default_factory=dict)
