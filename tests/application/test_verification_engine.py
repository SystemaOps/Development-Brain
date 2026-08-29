"""Unit tests for the Phase 13 verification engine."""

from __future__ import annotations

from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.verification import InMemoryVerificationRunRepository
from brain.adapters.verification.command_runner import FakeCommandRunner
from brain.application.verification_engine import VerificationEngine
from brain.domain.identity import new_execution_id, new_work_item_id
from brain.domain.verification_plan import (
    ArchitectureRule,
    CheckKind,
    VerificationVerdict,
)


def _engine(
    *,
    runner: FakeCommandRunner | None = None,
    architecture_rules: list[ArchitectureRule] | None = None,
    project_commands: dict[CheckKind, str] | None = None,
) -> tuple[VerificationEngine, FakeCommandRunner]:
    runner = runner or FakeCommandRunner()
    engine = VerificationEngine(
        runner=runner,
        results=InMemoryVerificationRunRepository(),
        code_graph=InMemoryCodeGraphRepository(),
        architecture_rules=architecture_rules,
        project_commands=project_commands,
    )
    return engine, runner


async def test_verdict_pass_when_all_checks_pass() -> None:
    engine, _ = _engine()
    outcome = await engine.verify(
        execution_id=new_execution_id(),
        work_item_id=new_work_item_id(),
        acceptance_criteria=["login works"],
        changed_files=["app/login.py"],
    )
    assert outcome.run.verdict == VerificationVerdict.PASS
    assert outcome.pr_readiness.pr_allowed is True


async def test_verdict_fail_when_command_fails() -> None:
    runner = FakeCommandRunner()
    runner.results["uv run pytest"] = {
        "command": "uv run pytest",
        "exit_code": 1,
        "stdout": "FAILED",
        "stderr": "",
    }
    engine, _ = _engine(
        runner=runner,
        project_commands={CheckKind.UNIT_TESTS: "uv run pytest"},
    )
    outcome = await engine.verify(
        execution_id=new_execution_id(),
        work_item_id=new_work_item_id(),
        acceptance_criteria=["login works"],
        changed_files=["app/login.py"],
    )
    assert outcome.run.verdict == VerificationVerdict.FAIL
    assert outcome.pr_readiness.pr_allowed is False
    assert outcome.run.feedback  # retry feedback present


async def test_verdict_fail_when_no_files_changed() -> None:
    engine, _ = _engine()
    outcome = await engine.verify(
        execution_id=new_execution_id(),
        work_item_id=new_work_item_id(),
        acceptance_criteria=["login works"],
        changed_files=[],
    )
    assert outcome.run.verdict == VerificationVerdict.FAIL
    assert outcome.pr_readiness.pr_allowed is False


async def test_architecture_rule_violation_fails() -> None:
    engine, _ = _engine(
        architecture_rules=[
            ArchitectureRule(
                name="services must not depend on db adapters",
                source_pattern=r"app/services/.*",
                target_pattern=r".*",
                relation="MUST_NOT_DEPEND_ON",
            )
        ]
    )
    outcome = await engine.verify(
        execution_id=new_execution_id(),
        work_item_id=new_work_item_id(),
        acceptance_criteria=["isolate services"],
        changed_files=["app/services/payment.py"],
    )
    architecture_step = next(s for s in outcome.run.plan.steps if s.kind == CheckKind.ARCHITECTURE)
    assert architecture_step.status.value == "fail"
    assert outcome.run.verdict == VerificationVerdict.FAIL


async def test_test_relevance_partial_when_missing_tests() -> None:
    engine, _ = _engine()
    outcome = await engine.verify(
        execution_id=new_execution_id(),
        work_item_id=new_work_item_id(),
        acceptance_criteria=["login works"],
        changed_files=["app/login.py"],
        repository_id=None,
        revision=None,
    )
    # Structural analysis with no expected set: no missing expected changes,
    # so structural passes; test relevance finds no relevant tests and passes.
    assert outcome.run.verdict == VerificationVerdict.PASS


async def test_verification_run_persisted() -> None:
    results = InMemoryVerificationRunRepository()
    runner = FakeCommandRunner()
    engine = VerificationEngine(
        runner=runner,
        results=results,
        code_graph=InMemoryCodeGraphRepository(),
    )
    outcome = await engine.verify(
        execution_id=new_execution_id(),
        work_item_id=new_work_item_id(),
        acceptance_criteria=["login works"],
        changed_files=["app/login.py"],
    )
    stored = await results.get_run(outcome.run.id)
    assert stored is not None
    assert stored.verdict == VerificationVerdict.PASS


async def test_pr_readiness_blocks_failed_verification() -> None:
    engine, _ = _engine()
    outcome = await engine.verify(
        execution_id=new_execution_id(),
        work_item_id=new_work_item_id(),
        acceptance_criteria=["login works"],
        changed_files=[],
    )
    assert outcome.pr_readiness.pr_allowed is False
    assert "no files changed" in " ".join(outcome.pr_readiness.reasons)
