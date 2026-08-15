"""Verification engine (Phase 13).

Independent verification that prevents code from reaching pull request solely
because the coding agent says it is complete.  The engine builds a
:class:`VerificationPlan` from the work item + acceptance criteria + changed
files + impact analysis, runs deterministic checks (command runner, structural
analysis, architecture rules, test relevance), aggregates a verdict
(PASS/PARTIAL/FAIL/BLOCKED), and applies the PR readiness gate (PASS -> PR
allowed; otherwise no automatic PR).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from brain.application.impact_analysis import ImpactAnalysisService
from brain.domain.identity import ExecutionId, RepositoryId, WorkItemId
from brain.domain.verification_plan import (
    ArchitectureRule,
    CheckKind,
    CheckStatus,
    PRReadiness,
    TestRelevanceReport,
    VerificationPlan,
    VerificationRun,
    VerificationStep,
    VerificationVerdict,
)
from brain.ports.code_intelligence import CodeGraphRepository
from brain.ports.verification import CommandRunner, VerificationRunRepository


@dataclass
class VerificationOutcome:
    run: VerificationRun
    pr_readiness: PRReadiness


class VerificationEngine:
    """Orchestrates verification plan -> checks -> verdict -> PR gate."""

    def __init__(
        self,
        *,
        runner: CommandRunner,
        results: VerificationRunRepository,
        code_graph: CodeGraphRepository,
        architecture_rules: list[ArchitectureRule] | None = None,
        project_commands: dict[CheckKind, str] | None = None,
    ) -> None:
        self._runner = runner
        self._results = results
        self._code_graph = code_graph
        self._architecture_rules = architecture_rules or []
        self._project_commands = project_commands or {}

    async def verify(
        self,
        *,
        execution_id: ExecutionId,
        work_item_id: WorkItemId,
        acceptance_criteria: list[str],
        changed_files: list[str],
        repository_id: RepositoryId | None = None,
        revision: str | None = None,
        workspace_path: str | None = None,
        persist: bool = True,
    ) -> VerificationOutcome:
        plan = self._build_plan(execution_id, work_item_id, acceptance_criteria, changed_files)
        run = VerificationRun(execution_id=execution_id, plan=plan)
        run.started_at = run.started_at

        # Task 13.2: deterministic commands.
        await self._run_command_steps(run, workspace_path=workspace_path)

        # Task 13.3: changed-file structural analysis vs expected impact.
        expected = set()
        if repository_id is not None and revision is not None:
            impact = ImpactAnalysisService(repository=self._code_graph)
            analysis = await impact.analyze(repository_id, revision, target_symbols=[])
            expected = set(analysis.related_files)
        run.plan.steps.append(self._structural_step(changed_files, expected))

        # Task 13.4: architecture rules.
        run.plan.steps.append(self._architecture_step(changed_files))

        # Task 13.5: test relevance.
        run.plan.steps.append(self._test_relevance_step(changed_files, expected))

        # Task 13.6/13.7: aggregate verdict + retry feedback.
        self._aggregate_verdict(run, acceptance_criteria, changed_files)

        # Task 13.9: PR readiness gate.
        readiness = self._pr_readiness(run)

        if persist:
            await self._results.save_run(run)
        return VerificationOutcome(run=run, pr_readiness=readiness)

    def _build_plan(
        self,
        execution_id: ExecutionId,
        work_item_id: WorkItemId,
        acceptance_criteria: list[str],
        changed_files: list[str],
    ) -> VerificationPlan:
        return VerificationPlan(
            execution_id=execution_id,
            work_item_id=work_item_id,
            steps=[],
            metadata={
                "acceptance_criteria": list(acceptance_criteria),
                "changed_files": list(changed_files),
            },
        )

    async def _run_command_steps(self, run: VerificationRun, *, workspace_path: str | None) -> None:
        for kind, command in self._project_commands.items():
            step = VerificationStep(kind=kind, name=kind.value, command=command)
            result = await self._runner.run(command, workspace_path=workspace_path)
            exit_code = _exit_code(result)
            step.output = str(result.get("stdout", "")) + str(result.get("stderr", ""))
            step.detail = {
                "exit_code": exit_code,
                "command": command,
            }
            step.status = CheckStatus.PASS if exit_code == 0 else CheckStatus.FAIL
            run.plan.steps.append(step)

    @staticmethod
    def _structural_step(changed_files: list[str], expected: set[str]) -> VerificationStep:
        missing = sorted(e for e in expected if e not in changed_files)
        step = VerificationStep(
            kind=CheckKind.STRUCTURAL,
            name="structural change analysis",
            detail={
                "changed_files": sorted(changed_files),
                "expected": sorted(expected),
                "missing": missing,
            },
        )
        step.status = CheckStatus.PASS if not missing else CheckStatus.FAIL
        if missing:
            step.output = f"missing expected changes: {', '.join(missing)}"
        return step

    def _architecture_step(self, changed_files: list[str]) -> VerificationStep:
        violations: list[str] = []
        for rule in self._architecture_rules:
            for path in changed_files:
                if _matches(path, rule.source_pattern):
                    violations.append(f"{path}: {rule.name} ({rule.relation})")
        step = VerificationStep(
            kind=CheckKind.ARCHITECTURE,
            name="architecture rule check",
            detail={"violations": violations},
        )
        step.status = CheckStatus.PASS if not violations else CheckStatus.FAIL
        if violations:
            step.output = "; ".join(violations)
        return step

    @staticmethod
    def _test_relevance_step(changed_files: list[str], expected: set[str]) -> VerificationStep:
        report = TestRelevanceReport(
            relevant_tests=sorted(path for path in expected if _is_test_path(path)),
            run_tests=[],
            modified_tests=sorted(path for path in changed_files if _is_test_path(path)),
            added_tests=[],
        )
        relevant = set(report.relevant_tests)
        modified = set(report.modified_tests)
        report.missing_tests = sorted(relevant - modified)
        step = VerificationStep(
            kind=CheckKind.TEST_RELEVANCE,
            name="test relevance check",
            detail=report.model_dump(mode="json"),
        )
        step.status = CheckStatus.PASS if not report.missing_tests else CheckStatus.PARTIAL
        if report.missing_tests:
            step.output = f"relevant tests not touched: {', '.join(report.missing_tests)}"
        return step

    @staticmethod
    def _aggregate_verdict(
        run: VerificationRun,
        acceptance_criteria: list[str],
        changed_files: list[str],
    ) -> None:
        issues: list[str] = []
        failed_steps = [step for step in run.plan.steps if step.status == CheckStatus.FAIL]
        partial_steps = [step for step in run.plan.steps if step.status == CheckStatus.PARTIAL]
        for step in failed_steps:
            issues.append(f"{step.name}: {step.output}")
        for step in partial_steps:
            issues.append(f"{step.name}: {step.output}")
        if not changed_files:
            issues.append("no files changed by execution")
        if not acceptance_criteria:
            issues.append("work item has no acceptance criteria to verify")

        run.issues = issues
        if failed_steps or not changed_files:
            run.verdict = VerificationVerdict.FAIL
        elif partial_steps:
            run.verdict = VerificationVerdict.PARTIAL
        elif not acceptance_criteria:
            run.verdict = VerificationVerdict.BLOCKED
        else:
            run.verdict = VerificationVerdict.PASS

        # Task 13.7: structured retry feedback.
        run.feedback = [f"{step.name}: {step.output}" for step in (*failed_steps, *partial_steps)]

    @staticmethod
    def _pr_readiness(run: VerificationRun) -> PRReadiness:
        if run.verdict == VerificationVerdict.PASS:
            return PRReadiness(
                run_id=run.id,
                verdict=run.verdict.value,
                pr_allowed=True,
                reasons=["all verification checks passed"],
            )
        return PRReadiness(
            run_id=run.id,
            verdict=run.verdict.value,
            pr_allowed=False,
            reasons=run.issues or [f"verdict is {run.verdict.value}"],
        )


def _matches(path: str, pattern: str) -> bool:
    return re.search(pattern, path) is not None


def _exit_code(result: dict[str, object]) -> int:
    value = result.get("exit_code", 0)
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return 1


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = [part.lower() for part in normalized.split("/")]
    if any(part in {"test", "tests", "spec", "specs", "__tests__"} for part in parts):
        return True
    name = normalized.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py")


__all__ = ["VerificationEngine", "VerificationOutcome"]
