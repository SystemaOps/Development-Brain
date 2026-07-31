from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from agent_core.agent_platform.agents.base.contracts import (
    AgentError,
    AgentErrorCategory,
    AgentNextAction,
    AgentRunStatus,
    ArtifactReference,
)
from agent_core.agent_platform.agents.base.workflow import (
    AgentWorkflowRuntime,
    persist_workflow_state,
)
from agent_core.agent_platform.agents.verification.config import (
    VerificationAgentConfig,
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
    TestAdequacyInput,
    TestAdequacySkill,
)
from agent_core.agent_platform.agents.verification.state import (
    VerificationAgentRequest,
    VerificationAgentResult,
    VerificationAgentState,
    VerificationFinding,
    VerificationVerdict,
)
from agent_core.agent_platform.runtime.dependency_container import (
    AgentDependencyContainer,
)
from agent_core.agent_platform.runtime.execution_context import (
    AgentExecutionContext,
)
from agent_core.domain.enums import CodingAttemptStatus


VERIFICATION_WORKFLOW_STEPS: tuple[str, ...] = (
    "load_task_acceptance_criteria",
    "load_coding_result",
    "inspect_repository_diff",
    "run_relevant_tests",
    "evaluate_acceptance_criteria",
    "review_regression_risk",
    "review_security_configuration",
    "summarize_evidence",
    "return_verdict",
)


class VerificationWorkflowState(BaseModel):
    request: VerificationAgentRequest
    agent_state: VerificationAgentState = Field(default_factory=VerificationAgentState)
    result: VerificationAgentResult | None = None


@dataclass(frozen=True)
class VerificationSkillSet:
    acceptance_evaluation: AcceptanceEvaluationSkill = field(
        default_factory=AcceptanceEvaluationSkill
    )
    test_adequacy: TestAdequacySkill = field(default_factory=TestAdequacySkill)
    regression_risk: RegressionRiskSkill = field(default_factory=RegressionRiskSkill)
    security_configuration: SecurityConfigurationReviewSkill = field(
        default_factory=SecurityConfigurationReviewSkill
    )
    evidence_summary: EvidenceSummarySkill = field(default_factory=EvidenceSummarySkill)


class VerificationAgentWorkflow:
    def __init__(
        self,
        *,
        config: VerificationAgentConfig,
        dependencies: AgentDependencyContainer,
    ) -> None:
        self.config = config
        self.dependencies = dependencies
        self.steps = VERIFICATION_WORKFLOW_STEPS
        self.skills = VerificationSkillSet()
        self.graph = _compile_verification_graph(self.skills)

    async def run(
        self,
        request: VerificationAgentRequest,
        context: AgentExecutionContext,
    ) -> VerificationAgentResult:
        output = await self.graph.ainvoke(
            VerificationWorkflowState(request=request),
            context=AgentWorkflowRuntime(
                config=self.config,
                dependencies=self.dependencies,
                execution_context=context,
            ),
        )
        state = VerificationWorkflowState.model_validate(output)
        if state.result is None:
            raise RuntimeError("Verification workflow completed without a result")
        return state.result


def build_verification_agent_workflow(
    config: VerificationAgentConfig,
    dependencies: AgentDependencyContainer,
) -> VerificationAgentWorkflow:
    return VerificationAgentWorkflow(config=config, dependencies=dependencies)


def _compile_verification_graph(skills: VerificationSkillSet):
    graph = StateGraph(
        VerificationWorkflowState,
        context_schema=AgentWorkflowRuntime,
    )
    graph.add_node("load_evidence", _load_evidence)
    graph.add_node("inspect_result", _inspect_result)
    graph.add_node(
        "inspect_quality_commands",
        partial(_inspect_quality_commands, skills=skills),
    )
    graph.add_node(
        "evaluate_acceptance_criteria",
        partial(_evaluate_acceptance_criteria, skills=skills),
    )
    graph.add_node("review_risk", partial(_review_risk, skills=skills))
    graph.add_node(
        "review_security_configuration",
        partial(_review_security_configuration, skills=skills),
    )
    graph.add_node("return_verdict", partial(_return_verdict, skills=skills))

    graph.add_edge(START, "load_evidence")
    graph.add_edge("load_evidence", "inspect_result")
    graph.add_edge("inspect_result", "inspect_quality_commands")
    graph.add_edge("inspect_quality_commands", "evaluate_acceptance_criteria")
    graph.add_edge("evaluate_acceptance_criteria", "review_risk")
    graph.add_edge("review_risk", "review_security_configuration")
    graph.add_edge("review_security_configuration", "return_verdict")
    graph.add_edge("return_verdict", END)
    return graph.compile(name="verification-agent-workflow")


async def _load_evidence(
    state: VerificationWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[VerificationAgentConfig]],
) -> dict:
    agent_state = _advance(state.agent_state, "load_evidence")
    await persist_workflow_state(runtime.context, agent_state)
    return {"agent_state": agent_state}


async def _inspect_result(
    state: VerificationWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[VerificationAgentConfig]],
) -> dict:
    request = state.request
    coding_result = request.coding_result
    diff = request.repository_diff or (coding_result.final_diff if coding_result else "")
    findings: list[VerificationFinding] = []

    if coding_result is None:
        findings.append(
            VerificationFinding(
                severity="blocked",
                code="missing_coding_result",
                message=("Verification cannot independently inspect a missing coding result."),
            )
        )
    elif coding_result.status == CodingAttemptStatus.BLOCKED:
        findings.append(
            VerificationFinding(
                severity="blocked",
                code="coding_blocked",
                message="Coding result is blocked and cannot be verified as complete.",
            )
        )
    elif coding_result.status != CodingAttemptStatus.SUCCEEDED:
        findings.append(
            VerificationFinding(
                severity="error",
                code="coding_not_successful",
                message="Coding result did not succeed.",
            )
        )

    if runtime.context.config.require_diff_for_pass and not diff.strip():
        findings.append(
            VerificationFinding(
                severity="blocked",
                code="missing_diff",
                message="Verification requires an actual repository diff.",
            )
        )

    agent_state = _with_findings(
        state.agent_state,
        phase="inspect_result",
        findings=findings,
    )
    await persist_workflow_state(runtime.context, agent_state)
    return {"agent_state": agent_state}


async def _inspect_quality_commands(
    state: VerificationWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[VerificationAgentConfig]],
    *,
    skills: VerificationSkillSet,
) -> dict:
    output = await skills.test_adequacy.run(
        TestAdequacyInput(
            coding_result=state.request.coding_result,
            test_evidence=state.request.test_evidence,
            require_test_command_for_pass=(runtime.context.config.require_test_command_for_pass),
            require_test_evidence_for_source_changes=(
                runtime.context.config.require_test_evidence_for_source_changes
            ),
        )
    )
    agent_state = _with_findings(
        state.agent_state,
        phase="inspect_quality_commands",
        findings=output.findings,
    )
    agent_state.test_adequacy = output.assessment
    await persist_workflow_state(runtime.context, agent_state)
    return {"agent_state": agent_state}


async def _evaluate_acceptance_criteria(
    state: VerificationWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[VerificationAgentConfig]],
    *,
    skills: VerificationSkillSet,
) -> dict:
    output = await skills.acceptance_evaluation.run(
        AcceptanceEvaluationInput(
            criteria=state.request.acceptance_criteria,
            evidence=_acceptance_evidence(state.request),
        )
    )
    agent_state = _with_findings(
        state.agent_state,
        phase="evaluate_acceptance_criteria",
        findings=output.findings,
    )
    agent_state.acceptance_coverage = output.assessment
    await persist_workflow_state(runtime.context, agent_state)
    return {"agent_state": agent_state}


async def _review_risk(
    state: VerificationWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[VerificationAgentConfig]],
    *,
    skills: VerificationSkillSet,
) -> dict:
    request = state.request
    coding_result = request.coding_result
    output = await skills.regression_risk.run(
        RegressionRiskInput(
            repository_diff=_repository_diff(request),
            evidence_text=_evidence_text(request),
            changed_files=(coding_result.changed_files if coding_result else []),
            rollback_available=(coding_result.rollback_plan.available if coding_result else None),
            warning_terms=runtime.context.config.warning_terms,
            sensitive_path_patterns=runtime.context.config.sensitive_path_patterns,
            large_change_line_threshold=(runtime.context.config.large_change_line_threshold),
            large_change_file_threshold=(runtime.context.config.large_change_file_threshold),
            warn_on_sensitive_changes=(runtime.context.config.warn_on_sensitive_changes),
            warn_on_missing_rollback=(runtime.context.config.warn_on_missing_rollback),
        )
    )
    agent_state = _with_findings(
        state.agent_state,
        phase="review_risk",
        findings=output.findings,
    )
    agent_state.regression_risk = output.assessment
    await persist_workflow_state(runtime.context, agent_state)
    return {"agent_state": agent_state}


async def _review_security_configuration(
    state: VerificationWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[VerificationAgentConfig]],
    *,
    skills: VerificationSkillSet,
) -> dict:
    output = await skills.security_configuration.run(
        SecurityConfigurationInput(
            repository_diff=_repository_diff(state.request),
            enabled=runtime.context.config.security_review_enabled,
        )
    )
    agent_state = _with_findings(
        state.agent_state,
        phase="review_security_configuration",
        findings=output.findings,
    )
    agent_state.security_review = output.assessment
    await persist_workflow_state(runtime.context, agent_state)
    return {"agent_state": agent_state}


async def _return_verdict(
    state: VerificationWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[VerificationAgentConfig]],
    *,
    skills: VerificationSkillSet,
) -> dict:
    request = state.request
    verdict = _verdict(state.agent_state.findings)
    status = AgentRunStatus.SUCCEEDED
    next_action = AgentNextAction.COMPLETE
    if verdict == VerificationVerdict.CHANGES_REQUESTED:
        status = AgentRunStatus.FAILED
        next_action = AgentNextAction.RUN_CODING
    elif verdict == VerificationVerdict.BLOCKED:
        status = AgentRunStatus.BLOCKED
        next_action = AgentNextAction.ESCALATE
    human_override_eligible = runtime.context.config.allows_human_override(verdict)
    if human_override_eligible:
        next_action = AgentNextAction.REQUEST_APPROVAL

    agent_state = _advance(
        state.agent_state,
        "completed",
        trace_step="return_verdict",
    )
    agent_state.verdict = verdict
    agent_state.human_override_eligible = human_override_eligible
    coding_result = request.coding_result
    summary_output = await skills.evidence_summary.run(
        EvidenceSummaryInput(
            repository_diff=_repository_diff(request),
            changed_files=(coding_result.changed_files if coding_result else []),
            external_test_evidence=request.test_evidence,
            acceptance_coverage=agent_state.acceptance_coverage,
            test_adequacy=agent_state.test_adequacy,
            regression_risk=agent_state.regression_risk,
            security_review=agent_state.security_review,
            findings=agent_state.findings,
        )
    )
    agent_state.evidence_summary = summary_output.summary
    state_ref = await persist_workflow_state(runtime.context, agent_state)
    result = VerificationAgentResult(
        execution_id=request.execution_id,
        project_id=request.project_id,
        task_id=request.task_id,
        status=status,
        summary=f"Verification completed with verdict: {verdict.value}.",
        output_artifacts=[
            ArtifactReference(
                artifact_id=f"verification:{request.execution_id}",
                artifact_type="verification_result",
                uri=(f"agent-state://{state_ref.namespace}/{state_ref.key}#verification"),
                title=f"Verification verdict: {verdict.value}",
            )
        ],
        evidence=(request.coding_result.evidence if request.coding_result else []),
        state=state_ref,
        next_action=next_action,
        errors=[
            AgentError(
                category=(
                    AgentErrorCategory.BLOCKED_ERROR
                    if verdict == VerificationVerdict.BLOCKED
                    else AgentErrorCategory.VALIDATION_ERROR
                ),
                message=finding.message,
                code=finding.code,
            )
            for finding in agent_state.findings
            if finding.severity in {"error", "blocked"}
        ],
        verdict=verdict,
        findings=agent_state.findings,
        acceptance_coverage=agent_state.acceptance_coverage,
        test_adequacy=agent_state.test_adequacy,
        regression_risk=agent_state.regression_risk,
        security_review=agent_state.security_review,
        evidence_summary=agent_state.evidence_summary,
        human_override_eligible=agent_state.human_override_eligible,
    )
    return {"agent_state": agent_state, "result": result}


def _with_findings(
    state: VerificationAgentState,
    *,
    phase: str,
    findings: list[VerificationFinding],
) -> VerificationAgentState:
    advanced = _advance(state, phase)
    advanced.findings = [*state.findings, *findings]
    return advanced


def _advance(
    state: VerificationAgentState,
    phase: str,
    *,
    trace_step: str | None = None,
) -> VerificationAgentState:
    return state.model_copy(
        deep=True,
        update={
            "phase": phase,
            "workflow_trace": [
                *state.workflow_trace,
                trace_step or phase,
            ],
        },
    )


def _verdict(findings: list[VerificationFinding]) -> VerificationVerdict:
    severities = {finding.severity for finding in findings}
    if "blocked" in severities:
        return VerificationVerdict.BLOCKED
    if "error" in severities:
        return VerificationVerdict.CHANGES_REQUESTED
    if "warning" in severities:
        return VerificationVerdict.PASSED_WITH_WARNINGS
    return VerificationVerdict.PASSED


def _evidence_text(request: VerificationAgentRequest) -> str:
    parts = list(request.test_evidence)
    if request.repository_diff:
        parts.append(request.repository_diff)
    if request.coding_result is not None:
        parts.append(request.coding_result.final_diff)
        for ref in request.coding_result.evidence:
            parts.append(ref.title or "")
            parts.append(ref.excerpt or "")
        for record in request.coding_result.command_results:
            parts.append(record.stdout)
            parts.append(record.stderr)
    return "\n".join(parts)


def _acceptance_evidence(
    request: VerificationAgentRequest,
) -> list[AcceptanceEvidence]:
    evidence = [
        AcceptanceEvidence(source=f"test_evidence:{index}", content=content)
        for index, content in enumerate(request.test_evidence, start=1)
    ]
    if request.repository_diff:
        evidence.append(
            AcceptanceEvidence(
                source="repository_diff",
                content=request.repository_diff,
            )
        )
    if request.coding_result is None:
        return evidence

    coding_result = request.coding_result
    evidence.append(
        AcceptanceEvidence(
            source="coding_result:final_diff",
            content=coding_result.final_diff,
        )
    )
    evidence.extend(
        AcceptanceEvidence(
            source=f"coding_result:evidence:{index}",
            content=f"{item.title or ''}\n{item.excerpt or ''}",
        )
        for index, item in enumerate(coding_result.evidence, start=1)
    )
    evidence.extend(
        AcceptanceEvidence(
            source=f"coding_result:command:{index}",
            content=f"{record.stdout}\n{record.stderr}",
        )
        for index, record in enumerate(coding_result.command_results, start=1)
    )
    return evidence


def _repository_diff(request: VerificationAgentRequest) -> str:
    if request.repository_diff:
        return request.repository_diff
    if request.coding_result is not None:
        return request.coding_result.final_diff
    return ""
