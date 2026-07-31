from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class VerificationVerdict(StrEnum):
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    CHANGES_REQUESTED = "changes_requested"
    BLOCKED = "blocked"


class VerificationFinding(BaseModel):
    severity: Literal["info", "warning", "error", "blocked"]
    code: str
    message: str
    acceptance_criterion_key: str | None = None


class AcceptanceCriterionOutcome(StrEnum):
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"


class AcceptanceCriterionAssessment(BaseModel):
    criterion_key: str
    statement: str
    verification_method: str
    mandatory: bool = True
    outcome: AcceptanceCriterionOutcome
    rationale: str
    matched_terms: list[str] = Field(default_factory=list)
    required_match_count: int = Field(default=0, ge=0)
    evidence_sources: list[str] = Field(default_factory=list)


class AcceptanceCoverageAssessment(BaseModel):
    criteria: list[AcceptanceCriterionAssessment] = Field(default_factory=list)
    total_count: int = Field(default=0, ge=0)
    satisfied_count: int = Field(default=0, ge=0)
    unsatisfied_count: int = Field(default=0, ge=0)
    mandatory_criteria_satisfied: bool = True


class QualityCommandOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class QualityCommandAssessment(BaseModel):
    command: tuple[str, ...]
    outcome: QualityCommandOutcome
    exit_code: int
    is_test_command: bool = False


class TestAdequacyAssessment(BaseModel):
    commands: list[QualityCommandAssessment] = Field(default_factory=list)
    quality_command_count: int = Field(default=0, ge=0)
    test_command_count: int = Field(default=0, ge=0)
    external_evidence_count: int = Field(default=0, ge=0)
    changed_source_files: list[str] = Field(default_factory=list)
    changed_test_files: list[str] = Field(default_factory=list)
    adequate: bool = True


class RegressionRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RegressionRiskFactor(BaseModel):
    code: str
    description: str
    score: int = Field(ge=0)
    affected_files: list[str] = Field(default_factory=list)


class RegressionRiskAssessment(BaseModel):
    level: RegressionRiskLevel = RegressionRiskLevel.LOW
    score: int = Field(default=0, ge=0, le=100)
    factors: list[RegressionRiskFactor] = Field(default_factory=list)
    changed_line_count: int = Field(default=0, ge=0)
    changed_files: list[str] = Field(default_factory=list)
    sensitive_files: list[str] = Field(default_factory=list)
    rollback_available: bool | None = None


class SecurityIssue(BaseModel):
    rule_id: str
    category: str
    severity: Literal["warning", "error"]
    message: str
    relative_path: str | None = None
    line_number: int | None = Field(default=None, ge=1)


class SecurityConfigurationAssessment(BaseModel):
    enabled: bool = True
    passed: bool = True
    issues: list[SecurityIssue] = Field(default_factory=list)
    scanned_added_line_count: int = Field(default=0, ge=0)


class VerificationEvidenceSummary(BaseModel):
    diff_present: bool = False
    changed_line_count: int = Field(default=0, ge=0)
    changed_files: list[str] = Field(default_factory=list)
    quality_command_count: int = Field(default=0, ge=0)
    test_command_count: int = Field(default=0, ge=0)
    external_test_evidence_count: int = Field(default=0, ge=0)
    acceptance_total_count: int = Field(default=0, ge=0)
    acceptance_satisfied_count: int = Field(default=0, ge=0)
    regression_risk: RegressionRiskLevel = RegressionRiskLevel.LOW
    security_issue_count: int = Field(default=0, ge=0)
    finding_counts: dict[str, int] = Field(default_factory=dict)
