from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from agent_core.agent_platform.agents.verification.contracts import (
    AcceptanceCoverageAssessment,
    RegressionRiskAssessment,
    SecurityConfigurationAssessment,
    TestAdequacyAssessment,
    VerificationEvidenceSummary,
    VerificationFinding,
)


class EvidenceSummaryInput(BaseModel):
    repository_diff: str = ""
    changed_files: list[str] = Field(default_factory=list)
    external_test_evidence: list[str] = Field(default_factory=list)
    acceptance_coverage: AcceptanceCoverageAssessment
    test_adequacy: TestAdequacyAssessment
    regression_risk: RegressionRiskAssessment
    security_review: SecurityConfigurationAssessment
    findings: list[VerificationFinding] = Field(default_factory=list)


class EvidenceSummaryOutput(BaseModel):
    summary: VerificationEvidenceSummary


class EvidenceSummarySkill:
    name = "evidence_summary"
    required_dependencies: tuple[str, ...] = ()

    async def run(self, input_data: EvidenceSummaryInput) -> EvidenceSummaryOutput:
        finding_counts = Counter(finding.severity for finding in input_data.findings)
        return EvidenceSummaryOutput(
            summary=VerificationEvidenceSummary(
                diff_present=bool(input_data.repository_diff.strip()),
                changed_line_count=input_data.regression_risk.changed_line_count,
                changed_files=sorted(input_data.changed_files),
                quality_command_count=input_data.test_adequacy.quality_command_count,
                test_command_count=input_data.test_adequacy.test_command_count,
                external_test_evidence_count=len(input_data.external_test_evidence),
                acceptance_total_count=input_data.acceptance_coverage.total_count,
                acceptance_satisfied_count=(input_data.acceptance_coverage.satisfied_count),
                regression_risk=input_data.regression_risk.level,
                security_issue_count=len(input_data.security_review.issues),
                finding_counts=dict(sorted(finding_counts.items())),
            )
        )
