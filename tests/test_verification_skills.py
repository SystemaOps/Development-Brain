from __future__ import annotations

import pytest

from agent_core.agent_platform.agents.verification import (
    AcceptanceCriterionOutcome,
    RegressionRiskLevel,
    VerificationAgentRequest,
    VerificationVerdict,
)
from agent_core.agent_platform.agents.verification.skills import (
    AcceptanceEvaluationInput,
    AcceptanceEvaluationSkill,
    AcceptanceEvidence,
    EvidenceSummaryInput,
    EvidenceSummarySkill,
    RegressionRiskInput,
    RegressionRiskSkill,
    SecurityConfigurationInput,
    SecurityConfigurationReviewSkill,
    TestAdequacyInput as AdequacyInput,
    TestAdequacySkill as AdequacySkill,
)
from agent_core.agent_platform.config import AgentConfig
from agent_core.agent_platform.factory import create_default_agent_factory
from agent_core.agent_platform.runtime import (
    AgentDependencyContainer,
    AgentExecutionContext,
    CheckpointIdentity,
)
from agent_core.domain.coding import (
    CodingAttemptResult,
    CommandExecutionRecord,
    RollbackPlan,
)
from agent_core.domain.enums import CodingAttemptStatus
from agent_core.schemas import AcceptanceCriterionSpec


def _coding_result(
    *,
    changed_files: list[str] | None = None,
    command_results: list[CommandExecutionRecord] | None = None,
    final_diff: str = "+return structured_verification_result\n",
    rollback_available: bool = True,
) -> CodingAttemptResult:
    files = changed_files or ["src/verification.py"]
    return CodingAttemptResult(
        task_key="task.verification-skills",
        repository_key="demo",
        attempt_number=1,
        status=CodingAttemptStatus.SUCCEEDED,
        changed_files=files,
        command_results=command_results or [],
        final_diff=final_diff,
        rollback_plan=RollbackPlan(
            available=rollback_available,
            strategy="reverse_diff",
            changed_files=files,
        ),
    )


def _criterion(
    key: str,
    statement: str,
    verification_method: str = "unit_test",
) -> AcceptanceCriterionSpec:
    return AcceptanceCriterionSpec(
        key=key,
        statement=statement,
        verification_method=verification_method,
    )


def _context(request: VerificationAgentRequest) -> AgentExecutionContext:
    checkpoint = CheckpointIdentity(
        project_id=request.project_id,
        workflow_id="verification-skills",
        agent_type="verification",
        agent_instance_id="verification:default",
        execution_id=request.execution_id,
        thread_id="demo:task.verification-skills:verification",
    )
    return AgentExecutionContext(
        execution_id=request.execution_id,
        project_id=request.project_id,
        task_id=request.task_id,
        workflow_id="verification-skills",
        agent_type="verification",
        agent_instance_id="verification:default",
        thread_id=checkpoint.thread_id,
        checkpoint=checkpoint,
        correlation_id="verification-skills",
    )


@pytest.mark.asyncio
async def test_acceptance_evaluation_builds_mandatory_coverage_matrix():
    output = await AcceptanceEvaluationSkill().run(
        AcceptanceEvaluationInput(
            criteria=[
                _criterion(
                    "ac.typed-result",
                    "API returns a structured verification result.",
                ),
                _criterion(
                    "ac.migration",
                    "Database migration preserves legacy records.",
                ),
            ],
            evidence=[
                AcceptanceEvidence(
                    source="repository_diff",
                    content="+return structured verification result from API",
                )
            ],
        )
    )

    assert output.assessment.total_count == 2
    assert output.assessment.satisfied_count == 1
    assert output.assessment.mandatory_criteria_satisfied is False
    assert output.assessment.criteria[0].outcome == AcceptanceCriterionOutcome.SATISFIED
    assert output.assessment.criteria[0].evidence_sources == ["repository_diff"]
    assert (
        output.assessment.criteria[1].outcome == AcceptanceCriterionOutcome.UNSATISFIED
    )
    assert output.findings[0].acceptance_criterion_key == "ac.migration"

    unverifiable = await AcceptanceEvaluationSkill().run(
        AcceptanceEvaluationInput(
            criteria=[_criterion("ac.vague", "OK")],
            evidence=[
                AcceptanceEvidence(
                    source="repository_diff",
                    content="+unrelated implementation",
                )
            ],
        )
    )
    assert unverifiable.assessment.mandatory_criteria_satisfied is False


@pytest.mark.asyncio
async def test_test_adequacy_reports_failed_commands_and_missing_test_evidence():
    failed_command = CommandExecutionRecord(
        command=("pytest", "tests/test_verification.py"),
        exit_code=1,
        stdout="1 failed",
        stderr="",
        duration_seconds=0.5,
    )
    output = await AdequacySkill().run(
        AdequacyInput(
            coding_result=_coding_result(command_results=[failed_command]),
            require_test_command_for_pass=True,
            require_test_evidence_for_source_changes=True,
        )
    )

    assert output.assessment.test_command_count == 1
    assert output.assessment.adequate is False
    assert {finding.code for finding in output.findings} == {"test_failure"}

    missing_output = await AdequacySkill().run(
        AdequacyInput(
            coding_result=_coding_result(),
            require_test_command_for_pass=True,
            require_test_evidence_for_source_changes=True,
        )
    )
    assert {finding.code for finding in missing_output.findings} == {
        "source_change_without_test_evidence",
        "test_command_missing",
    }


@pytest.mark.asyncio
async def test_regression_risk_records_sensitive_broad_and_unrecoverable_changes():
    output = await RegressionRiskSkill().run(
        RegressionRiskInput(
            repository_diff="+TODO remove fallback\n+new behavior\n-old behavior\n",
            evidence_text="",
            changed_files=["src/auth/service.py", "src/auth/policy.py"],
            rollback_available=False,
            warning_terms=["todo"],
            sensitive_path_patterns=["auth"],
            large_change_line_threshold=3,
            large_change_file_threshold=2,
            warn_on_sensitive_changes=True,
            warn_on_missing_rollback=True,
        )
    )

    assert output.assessment.level == RegressionRiskLevel.CRITICAL
    assert output.assessment.score == 90
    assert output.assessment.sensitive_files == [
        "src/auth/policy.py",
        "src/auth/service.py",
    ]
    assert {finding.code for finding in output.findings} == {
        "broad_file_change",
        "large_diff",
        "rollback_unavailable",
        "sensitive_files_changed",
        "warning_term_detected",
    }


@pytest.mark.asyncio
async def test_security_review_detects_added_defects_without_exposing_secret_value():
    secret_value = "sk-secret-value-123"
    repository_diff = f"""\
diff --git a/src/settings.py b/src/settings.py
--- a/src/settings.py
+++ b/src/settings.py
@@ -1,1 +1,4 @@
+api_key = "{secret_value}"
+client.get(url, verify=False)
+subprocess.run(command, shell=True)
+# eval(user_input) is documented but not executed
"""
    output = await SecurityConfigurationReviewSkill().run(
        SecurityConfigurationInput(repository_diff=repository_diff)
    )

    assert output.assessment.passed is False
    assert output.assessment.scanned_added_line_count == 4
    assert {issue.rule_id for issue in output.assessment.issues} == {
        "hardcoded_secret",
        "shell_execution_enabled",
        "tls_verification_disabled",
    }
    assert all(
        issue.relative_path == "src/settings.py" for issue in output.assessment.issues
    )
    assert secret_value not in output.model_dump_json()

    disabled = await SecurityConfigurationReviewSkill().run(
        SecurityConfigurationInput(
            repository_diff=repository_diff,
            enabled=False,
        )
    )
    assert disabled.assessment.enabled is False
    assert disabled.assessment.issues == []


@pytest.mark.asyncio
async def test_evidence_summary_aggregates_typed_skill_outputs():
    acceptance = await AcceptanceEvaluationSkill().run(
        AcceptanceEvaluationInput(
            criteria=[
                _criterion("ac.result", "Structured verification result exists.")
            ],
            evidence=[
                AcceptanceEvidence(
                    source="repository_diff",
                    content="+structured verification result exists",
                )
            ],
        )
    )
    test_adequacy = await AdequacySkill().run(
        AdequacyInput(coding_result=_coding_result())
    )
    regression = await RegressionRiskSkill().run(
        RegressionRiskInput(repository_diff="+structured verification result exists")
    )
    security = await SecurityConfigurationReviewSkill().run(
        SecurityConfigurationInput(
            repository_diff="+structured verification result exists"
        )
    )

    output = await EvidenceSummarySkill().run(
        EvidenceSummaryInput(
            repository_diff="+structured verification result exists",
            changed_files=["src/verification.py"],
            external_test_evidence=["targeted test passed"],
            acceptance_coverage=acceptance.assessment,
            test_adequacy=test_adequacy.assessment,
            regression_risk=regression.assessment,
            security_review=security.assessment,
            findings=[],
        )
    )

    assert output.summary.diff_present is True
    assert output.summary.acceptance_satisfied_count == 1
    assert output.summary.external_test_evidence_count == 1
    assert output.summary.security_issue_count == 0


@pytest.mark.asyncio
async def test_verification_agent_can_enforce_test_execution_from_configuration():
    dependencies = AgentDependencyContainer()
    factory = create_default_agent_factory(dependencies)
    agent = factory.create(
        agent_type="verification",
        config=AgentConfig(
            agent_type="verification",
            checkpoint_namespace="verification",
            settings={
                "require_test_command_for_pass": True,
                "require_test_evidence_for_source_changes": True,
            },
        ),
    )
    request = VerificationAgentRequest(
        project_id="demo",
        task_id="task.verification-skills",
        objective="Verify test adequacy.",
        coding_result=_coding_result(),
    )

    result = await agent.execute(request, _context(request))

    assert result.verdict == VerificationVerdict.CHANGES_REQUESTED
    assert result.test_adequacy.adequate is False
    assert result.evidence_summary.finding_counts == {"error": 2}
    assert {finding.code for finding in result.findings} == {
        "source_change_without_test_evidence",
        "test_command_missing",
    }


@pytest.mark.asyncio
async def test_verification_agent_requests_changes_for_security_defect():
    repository_diff = """\
diff --git a/src/client.py b/src/client.py
--- a/src/client.py
+++ b/src/client.py
@@ -1,1 +1,1 @@
+response = client.get(url, verify=False)
"""
    factory = create_default_agent_factory(AgentDependencyContainer())
    agent = factory.create(
        agent_type="verification",
        config=AgentConfig(
            agent_type="verification",
            checkpoint_namespace="verification",
        ),
    )
    request = VerificationAgentRequest(
        project_id="demo",
        task_id="task.verification-skills",
        objective="Verify transport security.",
        coding_result=_coding_result(
            changed_files=["src/client.py"],
            final_diff=repository_diff,
        ),
    )

    result = await agent.execute(request, _context(request))

    assert result.verdict == VerificationVerdict.CHANGES_REQUESTED
    assert result.security_review.passed is False
    assert result.evidence_summary.security_issue_count == 1
    assert [finding.code for finding in result.findings] == [
        "tls_verification_disabled"
    ]
