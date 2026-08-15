"""Verification plan domain model (Phase 13).

Independent verification: the coding executor must NOT decide its own result
is ready for a pull request.  This module carries the canonical plan of what
to check (deterministic commands, structural analysis, architecture rules,
test relevance), the individual check results, the aggregated verdict, and the
PR readiness decision (Tasks 13.1, 13.4, 13.5, 13.6, 13.8, 13.9).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import (
    ExecutionId,
    VerificationId,
    WorkItemId,
    new_verification_id,
)


class CheckKind(StrEnum):
    UNIT_TESTS = "unit_tests"
    INTEGRATION_TESTS = "integration_tests"
    LINT = "lint"
    FORMAT = "format"
    TYPE_CHECK = "type_check"
    BUILD = "build"
    STRUCTURAL = "structural"
    ARCHITECTURE = "architecture"
    TEST_RELEVANCE = "test_relevance"


class CheckStatus(StrEnum):
    PENDING = "pending"
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class VerificationVerdict(StrEnum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    BLOCKED = "blocked"


class VerificationPlan(BaseModel):
    """What to verify for one execution (Task 13.1)."""

    id: VerificationId = Field(default_factory=new_verification_id)
    execution_id: ExecutionId
    work_item_id: WorkItemId
    steps: list[VerificationStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, object] = Field(default_factory=dict)


class VerificationStep(BaseModel):
    """One check in the verification plan."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    kind: CheckKind
    name: str
    command: str | None = None
    status: CheckStatus = CheckStatus.PENDING
    output: str = ""
    detail: dict[str, object] = Field(default_factory=dict)


class VerificationRun(BaseModel):
    """Result of executing a verification plan."""

    id: VerificationId = Field(default_factory=new_verification_id)
    execution_id: ExecutionId
    plan: VerificationPlan
    verdict: VerificationVerdict = VerificationVerdict.PASS
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    issues: list[str] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list)
    pr_allowed: bool = False


class PRReadiness(BaseModel):
    """The gate decision (Task 13.9)."""

    run_id: VerificationId
    verdict: str
    pr_allowed: bool
    reasons: list[str] = Field(default_factory=list)


class ArchitectureRule(BaseModel):
    """Declarative architecture constraint (Task 13.4)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    source_pattern: str
    target_pattern: str
    relation: str = "MUST_NOT_DEPEND_ON"


class TestRelevanceReport(BaseModel):
    """Whether relevant tests were run/modified/added/missing (Task 13.5)."""

    relevant_tests: list[str] = Field(default_factory=list)
    run_tests: list[str] = Field(default_factory=list)
    modified_tests: list[str] = Field(default_factory=list)
    added_tests: list[str] = Field(default_factory=list)
    missing_tests: list[str] = Field(default_factory=list)


__all__ = [
    "ArchitectureRule",
    "CheckKind",
    "CheckStatus",
    "PRReadiness",
    "TestRelevanceReport",
    "VerificationPlan",
    "VerificationRun",
    "VerificationStep",
    "VerificationVerdict",
]
