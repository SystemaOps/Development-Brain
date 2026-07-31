from __future__ import annotations

from pydantic import BaseModel, Field

from agent_core.agent_platform.agents.verification.contracts import (
    RegressionRiskAssessment,
    RegressionRiskFactor,
    RegressionRiskLevel,
    VerificationFinding,
)


class RegressionRiskInput(BaseModel):
    repository_diff: str = ""
    evidence_text: str = ""
    changed_files: list[str] = Field(default_factory=list)
    rollback_available: bool | None = None
    warning_terms: list[str] = Field(default_factory=list)
    sensitive_path_patterns: list[str] = Field(default_factory=list)
    large_change_line_threshold: int = Field(default=500, ge=1)
    large_change_file_threshold: int = Field(default=20, ge=1)
    warn_on_sensitive_changes: bool = True
    warn_on_missing_rollback: bool = False


class RegressionRiskOutput(BaseModel):
    assessment: RegressionRiskAssessment
    findings: list[VerificationFinding] = Field(default_factory=list)


class RegressionRiskSkill:
    name = "regression_risk"
    required_dependencies: tuple[str, ...] = ()

    async def run(self, input_data: RegressionRiskInput) -> RegressionRiskOutput:
        combined_evidence = f"{input_data.repository_diff}\n{input_data.evidence_text}".lower()
        changed_line_count = _changed_line_count(input_data.repository_diff)
        sensitive_files = sorted(
            {
                path
                for path in input_data.changed_files
                if any(
                    pattern.lower() in path.lower()
                    for pattern in input_data.sensitive_path_patterns
                )
            }
        )
        factors: list[RegressionRiskFactor] = []
        findings: list[VerificationFinding] = []

        for term in input_data.warning_terms:
            if term.lower() not in combined_evidence:
                continue
            factors.append(
                RegressionRiskFactor(
                    code="warning_term_detected",
                    description=f"Warning term detected: {term}",
                    score=10,
                )
            )
            findings.append(
                VerificationFinding(
                    severity="warning",
                    code="warning_term_detected",
                    message=f"Verification found warning term: {term}",
                )
            )

        if sensitive_files:
            factors.append(
                RegressionRiskFactor(
                    code="sensitive_files_changed",
                    description="Changes affect sensitive configuration or boundary files.",
                    score=min(30, 10 + len(sensitive_files) * 5),
                    affected_files=sensitive_files,
                )
            )
            if input_data.warn_on_sensitive_changes:
                findings.append(
                    VerificationFinding(
                        severity="warning",
                        code="sensitive_files_changed",
                        message=(
                            "Changes affect sensitive files and require focused regression review."
                        ),
                    )
                )

        if changed_line_count >= input_data.large_change_line_threshold:
            factors.append(
                RegressionRiskFactor(
                    code="large_diff",
                    description=(
                        f"Diff changes {changed_line_count} lines, meeting the configured "
                        "large-change threshold."
                    ),
                    score=20,
                )
            )
            findings.append(
                VerificationFinding(
                    severity="warning",
                    code="large_diff",
                    message="The implementation diff is large enough to increase regression risk.",
                )
            )

        if len(input_data.changed_files) >= input_data.large_change_file_threshold:
            factors.append(
                RegressionRiskFactor(
                    code="broad_file_change",
                    description=(
                        f"Changes span {len(input_data.changed_files)} files, meeting the "
                        "configured breadth threshold."
                    ),
                    score=15,
                    affected_files=sorted(input_data.changed_files),
                )
            )
            findings.append(
                VerificationFinding(
                    severity="warning",
                    code="broad_file_change",
                    message="The implementation spans many files and needs broader regression testing.",
                )
            )

        if input_data.rollback_available is False:
            factors.append(
                RegressionRiskFactor(
                    code="rollback_unavailable",
                    description="The coding attempt does not provide an available rollback.",
                    score=25,
                )
            )
            if input_data.warn_on_missing_rollback:
                findings.append(
                    VerificationFinding(
                        severity="warning",
                        code="rollback_unavailable",
                        message="The coding attempt has no available rollback plan.",
                    )
                )

        score = min(100, sum(factor.score for factor in factors))
        assessment = RegressionRiskAssessment(
            level=_risk_level(score),
            score=score,
            factors=factors,
            changed_line_count=changed_line_count,
            changed_files=sorted(input_data.changed_files),
            sensitive_files=sensitive_files,
            rollback_available=input_data.rollback_available,
        )
        return RegressionRiskOutput(assessment=assessment, findings=findings)


def _changed_line_count(repository_diff: str) -> int:
    return sum(
        line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        for line in repository_diff.splitlines()
    )


def _risk_level(score: int) -> RegressionRiskLevel:
    if score >= 70:
        return RegressionRiskLevel.CRITICAL
    if score >= 40:
        return RegressionRiskLevel.HIGH
    if score >= 20:
        return RegressionRiskLevel.MEDIUM
    return RegressionRiskLevel.LOW
