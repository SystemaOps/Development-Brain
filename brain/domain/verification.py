"""Verification domain: independent evidence of correctness before PR.

Only a PASS verdict normally permits automatic pull-request creation.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import (
    EvidenceId,
    ExecutionId,
    VerificationId,
    new_verification_id,
)


class VerificationVerdict(StrEnum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    BLOCKED = "blocked"


class VerificationResult(BaseModel):
    id: VerificationId = Field(default_factory=new_verification_id)
    execution_id: ExecutionId
    verdict: VerificationVerdict
    requirement_results: list[dict[str, object]] = Field(default_factory=list)
    test_results: list[dict[str, object]] = Field(default_factory=list)
    architecture_results: list[dict[str, object]] = Field(default_factory=list)
    static_analysis_results: list[dict[str, object]] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceId] = Field(default_factory=list)
