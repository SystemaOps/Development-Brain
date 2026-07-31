from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent_core.agent_platform.agents.base.contracts import (
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from agent_core.agent_platform.agents.verification.contracts import (
    AcceptanceCoverageAssessment,
    RegressionRiskAssessment,
    SecurityConfigurationAssessment,
    TestAdequacyAssessment,
    VerificationEvidenceSummary,
    VerificationFinding,
    VerificationVerdict,
)
from agent_core.domain.coding import CodingAttemptResult
from agent_core.schemas import AcceptanceCriterionSpec


class VerificationAgentRequest(AgentRequest):
    agent_type: Literal["verification"] = "verification"
    acceptance_criteria: list[AcceptanceCriterionSpec] = Field(default_factory=list)
    coding_result: CodingAttemptResult | None = None
    repository_diff: str | None = None
    test_evidence: list[str] = Field(default_factory=list)


class VerificationAgentState(BaseModel):
    phase: str = "created"
    workflow_trace: list[str] = Field(default_factory=list)
    verdict: VerificationVerdict | None = None
    findings: list[VerificationFinding] = Field(default_factory=list)
    acceptance_coverage: AcceptanceCoverageAssessment = Field(
        default_factory=AcceptanceCoverageAssessment
    )
    test_adequacy: TestAdequacyAssessment = Field(default_factory=TestAdequacyAssessment)
    regression_risk: RegressionRiskAssessment = Field(default_factory=RegressionRiskAssessment)
    security_review: SecurityConfigurationAssessment = Field(
        default_factory=SecurityConfigurationAssessment
    )
    evidence_summary: VerificationEvidenceSummary = Field(
        default_factory=VerificationEvidenceSummary
    )
    human_override_eligible: bool = False


class VerificationAgentResult(AgentResult):
    agent_type: Literal["verification"] = "verification"
    status: AgentRunStatus
    verdict: VerificationVerdict
    findings: list[VerificationFinding] = Field(default_factory=list)
    acceptance_coverage: AcceptanceCoverageAssessment = Field(
        default_factory=AcceptanceCoverageAssessment
    )
    test_adequacy: TestAdequacyAssessment = Field(default_factory=TestAdequacyAssessment)
    regression_risk: RegressionRiskAssessment = Field(default_factory=RegressionRiskAssessment)
    security_review: SecurityConfigurationAssessment = Field(
        default_factory=SecurityConfigurationAssessment
    )
    evidence_summary: VerificationEvidenceSummary = Field(
        default_factory=VerificationEvidenceSummary
    )
    human_override_eligible: bool = False
