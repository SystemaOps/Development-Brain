from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import BaseModel, Field

from agent_core.agent_platform.agents.verification.contracts import (
    QualityCommandAssessment,
    QualityCommandOutcome,
    TestAdequacyAssessment,
    VerificationFinding,
)
from agent_core.domain.coding import CodingAttemptResult


_SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".swift",
    ".ts",
    ".tsx",
}
_TEST_RUNNERS = frozenset(
    {
        "jest",
        "mocha",
        "nox",
        "phpunit",
        "pytest",
        "rspec",
        "tox",
        "unittest",
        "vitest",
    }
)


class TestAdequacyInput(BaseModel):
    coding_result: CodingAttemptResult | None = None
    test_evidence: list[str] = Field(default_factory=list)
    require_test_command_for_pass: bool = False
    require_test_evidence_for_source_changes: bool = False


class TestAdequacyOutput(BaseModel):
    assessment: TestAdequacyAssessment
    findings: list[VerificationFinding] = Field(default_factory=list)


class TestAdequacySkill:
    name = "test_adequacy"
    required_dependencies: tuple[str, ...] = ()

    async def run(self, input_data: TestAdequacyInput) -> TestAdequacyOutput:
        result = input_data.coding_result
        changed_files = result.changed_files if result is not None else []
        changed_test_files = sorted(path for path in changed_files if _is_test_file(path))
        changed_source_files = sorted(
            path
            for path in changed_files
            if _is_source_file(path) and path not in changed_test_files
        )
        command_assessments = [
            QualityCommandAssessment(
                command=record.command,
                outcome=(
                    QualityCommandOutcome.TIMED_OUT
                    if record.timed_out
                    else (
                        QualityCommandOutcome.PASSED
                        if record.exit_code == 0
                        else QualityCommandOutcome.FAILED
                    )
                ),
                exit_code=record.exit_code,
                is_test_command=_is_test_command(record.command),
            )
            for record in (result.command_results if result is not None else [])
        ]
        findings = _command_findings(command_assessments)
        test_command_count = sum(command.is_test_command for command in command_assessments)

        if input_data.require_test_command_for_pass and test_command_count == 0:
            findings.append(
                VerificationFinding(
                    severity="error",
                    code="test_command_missing",
                    message="Verification requires evidence from an executed test command.",
                )
            )

        has_test_evidence = bool(
            test_command_count or input_data.test_evidence or changed_test_files
        )
        if (
            input_data.require_test_evidence_for_source_changes
            and changed_source_files
            and not has_test_evidence
        ):
            findings.append(
                VerificationFinding(
                    severity="error",
                    code="source_change_without_test_evidence",
                    message=(
                        "Source files changed without a test command, test artifact, "
                        "or corresponding test-file change."
                    ),
                )
            )

        assessment = TestAdequacyAssessment(
            commands=command_assessments,
            quality_command_count=len(command_assessments),
            test_command_count=test_command_count,
            external_evidence_count=len(input_data.test_evidence),
            changed_source_files=changed_source_files,
            changed_test_files=changed_test_files,
            adequate=not any(finding.severity in {"error", "blocked"} for finding in findings),
        )
        return TestAdequacyOutput(assessment=assessment, findings=findings)


def _command_findings(
    commands: list[QualityCommandAssessment],
) -> list[VerificationFinding]:
    findings: list[VerificationFinding] = []
    for command in commands:
        rendered = " ".join(command.command)
        if command.outcome == QualityCommandOutcome.TIMED_OUT:
            findings.append(
                VerificationFinding(
                    severity="error",
                    code="test_timeout",
                    message=f"Quality command timed out: {rendered}",
                )
            )
        elif command.outcome == QualityCommandOutcome.FAILED:
            findings.append(
                VerificationFinding(
                    severity="error",
                    code="test_failure",
                    message=f"Quality command failed: {rendered}",
                )
            )
    return findings


def _is_test_command(command: tuple[str, ...]) -> bool:
    lowered = [PurePosixPath(part.lower().replace("\\", "/")).name for part in command]
    if any(part in _TEST_RUNNERS for part in lowered):
        return True
    return "test" in lowered or any(part.startswith("test:") for part in lowered)


def _is_test_file(path: str) -> bool:
    normalized = path.lower().replace("\\", "/")
    pure_path = PurePosixPath(normalized)
    parts = set(pure_path.parts)
    return (
        bool(parts & {"test", "tests", "spec", "specs"})
        or pure_path.name.startswith("test_")
        or pure_path.stem.endswith(("_test", ".spec", ".test"))
    )


def _is_source_file(path: str) -> bool:
    return PurePosixPath(path.lower().replace("\\", "/")).suffix in _SOURCE_SUFFIXES
