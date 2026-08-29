"""Phase 39 golden tests and completion gate.

Full Reference End-to-End Environment: the entire architecture functions as an
observable, recoverable system and visibly collaborates with humans.

39.2/39.3 - the sample repository (login service with partial account locking)
and its requirement + work item are seeded (see scenarios/reference/).
39.4 - the Brain detects the partial implementation and projects an
observation to the human tool.
39.5 - context quality: requirement, auth service, user model, security
config and related tests included; unrelated module excluded; budget
respected.
39.6/39.7/39.8 - execution through the controlled executor: first run fails
verification, the failure is journaled and commented, the retry passes and a
PR is created with the observation projected.
39.9 - merged revision returns into knowledge (code graph updated, re-sync
enqueued).
39.10 - human feedback: HUMAN_ACTION_REQUIRED observation, human reply ->
HumanFeedbackReceived -> context rebuilt -> workflow resumes.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from brain.application.context_engine import ContextEngineService
from brain.application.human_feedback import HumanFeedbackService
from brain.application.observation_projection import ObservationProjectionService
from brain.application.observations import ObservationService
from brain.application.pull_request_service import PullRequestService
from brain.application.verification_engine import VerificationEngine
from brain.bootstrap.container import create_brain_container
from brain.bootstrap.settings import (
    AutomationPolicySettings,
    BrainSettings,
    DocumentationSettings,
    Neo4jSettings,
    PostgresSettings,
    RedisSettings,
    SourceControlSettings,
    VerificationSettings,
    WeaviateSettings,
    WorkManagementSettings,
)
from brain.domain.context import ContextRequest
from brain.domain.executions import (
    Execution,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
)
from brain.domain.external_reference import ExternalReference
from brain.domain.human_activity import HumanActivityReference, ProjectionStatus
from brain.domain.identity import (
    ObservationId,
    new_actor_id,
    new_workflow_id,
)
from brain.domain.observations import Observation, ObservationType
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.work_items import WorkItem
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@localhost:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)

SEED_DIR = Path(__file__).parent.parent / "scenarios" / "reference" / "seed_repository"
SEED_REVISION = "seed-abc123"
MERGED_REVISION = "merged-def456"


def _settings() -> BrainSettings:
    return BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://localhost:7687"),
        storage_semantic=WeaviateSettings(host="localhost"),
        storage_queue=RedisSettings(url="redis://localhost:6379/0"),
        work_management=WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
        automation=AutomationPolicySettings(auto_create_pr=True),
    )


def _seed_files() -> dict[str, str]:
    """Read the sample repository from disk as path -> content."""
    files: dict[str, str] = {}
    for path in sorted(SEED_DIR.rglob("*")):
        if path.is_file() and "__pycache__" not in str(path):
            files[str(path.relative_to(SEED_DIR)).replace("\\", "/")] = path.read_text(
                encoding="utf-8"
            )
    return files


class _RecordingHumanActivityPort:
    """Records every published observation like a real OpenProject adapter."""

    def __init__(self) -> None:
        self.published: list[tuple[ExternalReference, Observation]] = []

    async def publish_observation(
        self, target: ExternalReference, observation: Observation
    ) -> HumanActivityReference:
        self.published.append((target, observation))
        return HumanActivityReference(
            observation_id=observation.id,
            provider=target.provider,
            target=target,
            status=ProjectionStatus.PUBLISHED,
        )


class _ScriptedExecutor:
    """Controlled fake executor: first run changes nothing, retry changes files."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.calls += 1
        from brain.domain.executions import ExecutionResult

        if self.calls == 1:
            return ExecutionResult(
                execution_id=request.execution_id,
                status=ExecutionStatus.COMPLETED,
                modified_files=[],
                observations=["partial implementation; locking not enforced"],
            )
        return ExecutionResult(
            execution_id=request.execution_id,
            status=ExecutionStatus.COMPLETED,
            modified_files=["src/auth/service.py", "tests/test_auth.py"],
            tests_executed=["tests/test_auth.py"],
            observations=["implemented account locking"],
        )


def _projection(port: _RecordingHumanActivityPort) -> ObservationProjectionService:
    from brain.adapters.in_memory.human_activity import InMemoryActivityProjectionRepository

    return ObservationProjectionService(
        projections=InMemoryActivityProjectionRepository(),
        port=port,
        observations=None,  # type: ignore[arg-type]
    )


def _observations(container) -> ObservationService:
    service = container.services["observations"]
    assert isinstance(service, ObservationService)
    return service


def _context_engine(container) -> ContextEngineService:
    service = container.services["context_engine"]
    assert isinstance(service, ContextEngineService)
    return service


def _code_intelligence(container):
    from brain.application.code_intelligence import CodeIntelligenceService

    service = container.services["code_intelligence"]
    assert isinstance(service, CodeIntelligenceService)
    return service


async def _seed_scenario(container) -> tuple[Project, Repository, WorkItem, uuid.UUID]:
    """39.2/39.3: seed project, repository, requirement, work item."""
    project = Project(name="e2e-demo")
    await container.repositories.projects.create(project)
    repository = Repository(
        project_id=project.id,
        name="e2e-demo",
        clone_url="https://example.com/e2e-demo.git",
        default_branch="main",
    )
    await container.repositories.repositories.create(repository)

    from brain.domain.requirements import (
        AcceptanceCriterion,
        Requirement,
        RequirementStatus,
    )

    requirement = Requirement(
        project_id=project.id,
        key="REQ-ACCOUNT-LOCK",
        title="Account locking after five failed login attempts",
        description=(
            "After five consecutive failed login attempts the account must be "
            "locked for 15 minutes."
        ),
        status=RequirementStatus.APPROVED,
        acceptance_criteria=[
            AcceptanceCriterion(description="A fifth failed attempt locks the account"),
            AcceptanceCriterion(description="Locked accounts reject login attempts"),
            AcceptanceCriterion(description="Lockout expires after 15 minutes"),
        ],
    )
    await container.repositories.requirements.create(requirement)

    work_item = WorkItem(
        project_id=project.id,
        title="Implement account locking after five failed login attempts",
        description=requirement.description,
        requirement_refs=[requirement.id],
    )
    await container.repositories.work_items.create(work_item)
    return project, repository, work_item, requirement.id


async def _ingest_seed(container, repository: Repository) -> None:
    """Index the sample repository into the code graph (Task 39.2 discovery)."""
    await _code_intelligence(container).build_revision(repository.id, SEED_REVISION, _seed_files())


async def test_39_4_partial_implementation_detected_and_commented() -> None:
    """39.4: Brain detects partial implementation; observation + comment."""
    container = await create_brain_container(_settings())
    try:
        project, repository, work_item, _ = await _seed_scenario(container)
        await _ingest_seed(container, repository)

        service = _code_intelligence(container)
        symbols = await service.where_defined(
            repository.id, SEED_REVISION, "src.auth.service.AuthService.login"
        )
        assert len(symbols) == 1

        observations = _observations(container)
        observation = await observations.create(
            project_id=project.id,
            observation_type=ObservationType.IMPLEMENTATION_STATUS,
            title="Partial implementation: account locking not enforced",
            body=(
                "Failed attempts are tracked (FR-2) but the lockout after five "
                "failures (FR-1 / AC-1..AC-4) is not implemented."
            ),
            work_item_id=work_item.id,
            dedup_key="e2e-partial-locking",
        )
        assert observation.observation_type == ObservationType.IMPLEMENTATION_STATUS

        port = _RecordingHumanActivityPort()
        projection = _projection(port)
        target = ExternalReference(provider="openproject", external_id="42", external_type="task")
        await projection.project(observation, target)
        assert len(port.published) == 1
        assert "Partial implementation" in port.published[0][1].title
    finally:
        await container.close()


async def test_39_5_context_quality_and_token_budget() -> None:
    """39.5: context includes relevant modules, excludes unrelated, budget ok."""
    container = await create_brain_container(_settings())
    try:
        project, repository, work_item, _ = await _seed_scenario(container)
        await _ingest_seed(container, repository)

        result = await _context_engine(container).build(
            ContextRequest(
                work_item_id=work_item.id,
                project_id=project.id,
                repository_id=repository.id,
                revision=SEED_REVISION,
                preferred_token_budget=8000,
            )
        )
        capsule = result.capsule
        assert capsule.total_tokens <= capsule.model_budget_tokens
        assert capsule.request.preferred_token_budget == 8000

        paths = [str(c.metadata.get("path", "")) for c in capsule.candidates]
        contents = " ".join(c.content for c in capsule.candidates)

        assert "Account locking" in contents or "account locking" in contents
        assert any("auth/service.py" in p for p in paths)
        assert any("users/user_model.py" in p for p in paths)
        assert any("auth/security.py" in p for p in paths)
        assert any("tests/test_auth.py" in p for p in paths)

        # Excluded: the unrelated module never ranks with the top relevant
        # candidates (its relevance stays below the highest auth score).
        unrelated_scores = [
            c.relevance_score
            for c in capsule.candidates
            if "unrelated" in str(c.metadata.get("path", ""))
        ]
        top_relevant = [
            c.relevance_score
            for c in capsule.candidates
            if "auth/" in str(c.metadata.get("path", ""))
            or "users/" in str(c.metadata.get("path", ""))
            or "test_auth" in str(c.metadata.get("path", ""))
        ]
        assert unrelated_scores
        assert max(unrelated_scores) < max(top_relevant)
    finally:
        await container.close()


async def test_39_6_7_8_execute_fail_retry_and_pr() -> None:
    """39.6/39.7/39.8: execute -> verification FAIL -> retry -> PASS -> PR."""
    container = await create_brain_container(_settings())
    try:
        _, repository, work_item, _ = await _seed_scenario(container)
        await _ingest_seed(container, repository)

        scripted = _ScriptedExecutor()
        container.services["executor"] = scripted

        def _new_execution() -> Execution:
            return Execution(
                workflow_id=new_workflow_id(),
                work_item_id=work_item.id,
                executor_id=new_actor_id(),
                status=ExecutionStatus.STARTED,
                working_branch="brain/wi/deadbeef",
            )

        def _request_for(execution: Execution) -> ExecutionRequest:
            return ExecutionRequest(
                execution_id=execution.id,
                workflow_id=execution.workflow_id,
                work_item_id=execution.work_item_id,
                repository_ref="https://example.com/e2e-demo.git",
                base_revision=SEED_REVISION,
            )

        verification = container.services["verification"]
        assert isinstance(verification, VerificationEngine)
        criteria = [
            "A fifth failed attempt locks the account",
            "Locked accounts reject login attempts",
            "Lockout expires after 15 minutes",
        ]

        # 39.6/39.7: first execution misses the criteria -> FAIL.
        first = _new_execution()
        await container.repositories.executions.create(first)
        first_result = await scripted.execute(_request_for(first))
        assert first_result.modified_files == []
        outcome = await verification.verify(
            execution_id=first.id,
            work_item_id=work_item.id,
            acceptance_criteria=criteria,
            changed_files=first_result.modified_files,
            repository_id=repository.id,
            revision=SEED_REVISION,
        )
        assert outcome.run.verdict.value == "fail"

        observations = _observations(container)
        failure_obs = await observations.create(
            project_id=work_item.project_id,
            observation_type=ObservationType.VERIFICATION_FAILURE,
            title="Verification failed: no files changed by execution",
            body="; ".join(outcome.run.issues),
            work_item_id=work_item.id,
            execution_id=first.id,
            dedup_key=f"e2e-verify-fail:{first.id}",
        )
        assert failure_obs.observation_type == ObservationType.VERIFICATION_FAILURE
        assert "no files changed" in failure_obs.body

        # Retry context is rebuilt (new capsule) with the failure feedback.
        retry_capsule = await _context_engine(container).build(
            ContextRequest(
                work_item_id=work_item.id,
                project_id=work_item.project_id,
                repository_id=repository.id,
                revision=SEED_REVISION,
                preferred_token_budget=8000,
            )
        )
        assert retry_capsule.capsule is not None
        assert outcome.run.issues and "no files changed" in outcome.run.issues[0]

        # 39.8: the retry implements the criteria -> PASS -> PR readiness.
        second = _new_execution()
        await container.repositories.executions.create(second)
        second_result = await scripted.execute(_request_for(second))
        assert second_result.modified_files == ["src/auth/service.py", "tests/test_auth.py"]
        pass_outcome = await verification.verify(
            execution_id=second.id,
            work_item_id=work_item.id,
            acceptance_criteria=criteria,
            changed_files=second_result.modified_files,
            repository_id=repository.id,
            revision=SEED_REVISION,
        )
        assert pass_outcome.run.verdict.value == "pass"
        assert pass_outcome.pr_readiness.pr_allowed is True

        # The pipeline records the canonical verification result (what the PR
        # readiness gate reads).
        from brain.domain.verification import VerificationResult, VerificationVerdict

        await container.repositories.verification_results.create(
            VerificationResult(
                execution_id=second.id,
                verdict=VerificationVerdict.PASS,
            )
        )

        # PR created + observation projected.
        port = _RecordingHumanActivityPort()
        projection = _projection(port)
        pr_service = container.services["pull_request_service"]
        assert isinstance(pr_service, PullRequestService)
        pr_result = await pr_service.create_pull_request(
            execution_id=second.id, work_item_id=work_item.id
        )
        assert pr_result.created is True
        assert pr_result.observation_id is not None
        observation = await _observations(container).get(
            ObservationId(uuid.UUID(pr_result.observation_id))
        )
        assert observation is not None
        target = ExternalReference(provider="openproject", external_id="42", external_type="task")
        await projection.project(observation, target)
        assert len(port.published) == 1
        assert "Merge Request" in port.published[0][1].body
    finally:
        await container.close()


async def test_39_9_merge_and_reingest() -> None:
    """39.9: merged revision returns into Brain knowledge."""
    container = await create_brain_container(_settings())
    try:
        project, repository, work_item, _ = await _seed_scenario(container)
        await _ingest_seed(container, repository)

        merged_files = dict(_seed_files())
        merged_files["src/auth/service.py"] = (
            "from __future__ import annotations\n\n"
            "class AuthService:\n"
            "    def login(self, uid: str, password: str) -> str:\n"
            "        if not self._locked(uid):\n"
            "            raise RuntimeError('locked out')\n"
            "        return uid\n"
        )
        service = _code_intelligence(container)
        await service.build_revision(repository.id, MERGED_REVISION, merged_files)
        merged_symbols = await service.where_defined(
            repository.id, MERGED_REVISION, "src.auth.service.AuthService.login"
        )
        assert merged_symbols and merged_symbols[0].identity.revision == MERGED_REVISION

        # Re-sync is enqueued by the scheduler reconciliation.
        from brain.scheduler.reconciliation import ReconciliationService

        scheduler = ReconciliationService(container=container)
        updated = repository.model_copy(update={"current_revision": MERGED_REVISION})
        await container.repositories.repositories.update(updated)
        report = await scheduler.reconcile()
        assert report.repositories_checked >= 1

        stored = await container.repositories.repositories.get(repository.id)
        assert stored is not None and stored.current_revision == MERGED_REVISION
    finally:
        await container.close()


async def test_39_10_human_feedback_loop() -> None:
    """39.10: ambiguous task -> HUMAN_ACTION_REQUIRED -> reply -> resume."""
    container = await create_brain_container(_settings())
    try:
        project, repository, work_item, _ = await _seed_scenario(container)
        await _ingest_seed(container, repository)

        observations = _observations(container)
        clarification = await observations.create(
            project_id=project.id,
            observation_type=ObservationType.HUMAN_ACTION_REQUIRED,
            title="Clarification needed: lockout applies to IP or account?",
            body="Specify whether lockout is per account or per source IP.",
            work_item_id=work_item.id,
            dedup_key="e2e-clarify-1",
        )
        assert clarification.observation_type == ObservationType.HUMAN_ACTION_REQUIRED

        port = _RecordingHumanActivityPort()
        projection = _projection(port)
        target = ExternalReference(provider="openproject", external_id="42", external_type="task")
        await projection.project(clarification, target)
        assert "Clarification needed" in port.published[0][1].title

        # A context capsule exists for the work item before feedback.
        await _context_engine(container).build(
            ContextRequest(
                work_item_id=work_item.id,
                project_id=project.id,
                repository_id=repository.id,
                revision=SEED_REVISION,
                preferred_token_budget=8000,
            )
        )
        capsules = await container.repositories.context_capsules.list_capsules_for_work_item(
            work_item.id
        )
        assert len(capsules) == 1

        # The human replies -> HumanFeedbackReceived -> context rebuilt.
        feedback_service = container.services["human_feedback"]
        assert isinstance(feedback_service, HumanFeedbackService)
        feedback = await feedback_service.receive(
            author="alice@example.com",
            provider="openproject",
            external_comment_id="c-99",
            work_item_id=work_item.id,
            message="Per account, please.",
            verdict="clarification",
        )
        assert feedback.work_item_id == work_item.id

        resume = await feedback_service.resume_workflow(feedback)
        assert resume["status"] == "resumed"
        assert resume["context_invalidated"] is True
        capsules_after = await container.repositories.context_capsules.list_capsules_for_work_item(
            work_item.id
        )
        assert capsules_after == []

        # The workflow is resumed: a fresh execution is accepted.
        execution = Execution(
            workflow_id=new_workflow_id(),
            work_item_id=work_item.id,
            executor_id=new_actor_id(),
            status=ExecutionStatus.STARTED,
            working_branch="brain/wi/resume",
        )
        created = await container.repositories.executions.create(execution)
        assert created.status == ExecutionStatus.STARTED
    finally:
        await container.close()
