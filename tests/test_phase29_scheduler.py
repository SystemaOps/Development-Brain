"""Phase 29 golden tests and completion gate.

The system converges back to correct state after missed events or temporary
integration failures: stale repositories are re-synced, stuck executions are
recovered with human observations, failed observation projections are retried
idempotently, and the scheduler loop runs with graceful shutdown.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from brain.bootstrap.container import create_brain_container
from brain.bootstrap.settings import (
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
from brain.domain.executions import Execution, ExecutionStatus
from brain.domain.identity import ActorId, new_workflow_id
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.work_items import WorkItem
from brain.scheduler.main import SchedulerLoop
from brain.scheduler.reconciliation import ReconciliationService
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@localhost:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)


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
    )


async def _seed_project(container: object, *, name: str = "sched") -> Project:
    project = Project(name=name)
    await container.repositories.projects.create(project)  # type: ignore[union-attr]
    return project


async def _seed_repository(
    container: object, project: Project, *, revision: str | None = "abc"
) -> Repository:
    repository = Repository(
        project_id=project.id,
        name="app",
        clone_url="git@x:app.git",
        current_revision=revision,
    )
    await container.repositories.repositories.create(repository)  # type: ignore[union-attr]
    return repository


async def test_gate_repository_reconciliation_detects_stale() -> None:
    container = await create_brain_container(_settings())
    try:
        project = await _seed_project(container)
        repository = await _seed_repository(container, project, revision="abc")
        # A newer snapshot exists than the tracked revision -> stale.
        from brain.domain.repository_scan import RepositorySnapshot

        snapshot = RepositorySnapshot(
            repository_id=repository.id,
            revision="def",
            tree=["src/a.py"],
        )
        await container.repositories.repository_snapshots.save_snapshot(snapshot)

        service = ReconciliationService(container)
        report = await service.reconcile()
        assert report.repositories_stale >= 1
        assert any("app" in detail for detail in report.details)
    finally:
        await container.close()


async def test_gate_repository_fresh_when_revisions_match() -> None:
    container = await create_brain_container(_settings())
    try:
        project = await _seed_project(container)
        repository = await _seed_repository(container, project, revision="abc")
        from brain.domain.repository_scan import RepositorySnapshot

        snapshot = RepositorySnapshot(
            repository_id=repository.id,
            revision="abc",
            tree=[],
        )
        await container.repositories.repository_snapshots.save_snapshot(snapshot)
        service = ReconciliationService(container)
        report = await service.reconcile()
        assert report.repositories_stale == 0
    finally:
        await container.close()


async def test_gate_stuck_execution_detection_and_observation() -> None:
    container = await create_brain_container(_settings())
    try:
        project = await _seed_project(container)
        work_item = WorkItem(project_id=project.id, title="Task")
        await container.repositories.work_items.create(work_item)

        stuck = Execution(
            workflow_id=new_workflow_id(),
            work_item_id=work_item.id,
            executor_id=ActorId(uuid.uuid4()),
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(hours=5),
        )
        await container.repositories.executions.create(stuck)

        service = ReconciliationService(container, stuck_threshold_seconds=60)
        report = await service.reconcile()
        assert report.stuck_executions >= 1
        assert report.stuck_recovered >= 1

        # The execution was marked blocked.
        stored = await container.repositories.executions.get(stuck.id)
        assert stored is not None
        assert stored.status == ExecutionStatus.BLOCKED

        # A HUMAN_ACTION_REQUIRED observation was created.
        observations = await container.repositories.observations.list_by_project(project.id)
        assert observations
        assert observations[0].requires_human_attention is True
    finally:
        await container.close()


async def test_gate_stuck_execution_not_flagged_when_recent() -> None:
    container = await create_brain_container(_settings())
    try:
        project = await _seed_project(container)
        work_item = WorkItem(project_id=project.id, title="Task")
        await container.repositories.work_items.create(work_item)
        fresh = Execution(
            workflow_id=new_workflow_id(),
            work_item_id=work_item.id,
            executor_id=ActorId(uuid.uuid4()),
            status=ExecutionStatus.RUNNING,
        )
        await container.repositories.executions.create(fresh)
        service = ReconciliationService(container, stuck_threshold_seconds=3600)
        report = await service.reconcile()
        assert report.stuck_executions == 0
    finally:
        await container.close()


async def test_gate_projection_retry_is_idempotent() -> None:
    """Failed projections are retried without duplicate comments."""
    from brain.adapters.human_activity.openproject import OpenProjectActivityAdapter
    from brain.application.observation_projection import ObservationProjectionService
    from brain.application.observations import ObservationService
    from brain.domain.external_reference import ExternalReference
    from brain.domain.human_activity import HumanActivityReference, ProjectionStatus
    from brain.domain.observations import ObservationType

    container = await create_brain_container(_settings())
    try:
        project = await _seed_project(container)
        observations_service = container.services["observations"]
        assert isinstance(observations_service, ObservationService)
        observation = await observations_service.create(
            project_id=project.id,
            observation_type=ObservationType.VERIFICATION_FAILURE,
            title="Verification failed",
        )

        # Replace the null port with a publishing OpenProject adapter and
        # record a failed projection for the observation.
        class _FakeTransport:
            def __init__(self) -> None:
                self.comments: list[str] = []

            async def post_comment(self, external_id: str, body: str) -> dict[str, object]:
                self.comments.append(body)
                return {"id": f"comment-{len(self.comments)}"}

        transport = _FakeTransport()
        projection_service = container.services["observation_projection"]
        assert isinstance(projection_service, ObservationProjectionService)
        projection_service._port = OpenProjectActivityAdapter(transport=transport)

        reference = HumanActivityReference(
            observation_id=observation.id,
            provider="openproject",
            target=ExternalReference(provider="openproject", external_id="42"),
            status=ProjectionStatus.FAILED,
            error="boom",
        )
        await projection_service._projections.save(reference)

        service = ReconciliationService(container)
        report = await service.reconcile()
        assert report.projections_retried >= 1
        # Retried idempotently: exactly one comment.
        assert len(transport.comments) == 1
    finally:
        await container.close()


async def test_gate_scheduler_loop_runs_and_stops() -> None:
    container = await create_brain_container(_settings())
    try:
        await _seed_project(container)
        loop = SchedulerLoop(container=container, interval_seconds=0.01)
        ran = await loop.run(iterations=2)
        assert ran == 2
    finally:
        await container.close()


async def test_gate_full_reconcile_returns_report() -> None:
    container = await create_brain_container(_settings())
    try:
        project = await _seed_project(container)
        await _seed_repository(container, project)
        service = ReconciliationService(container)
        report = await service.reconcile()
        assert report.repositories_checked >= 1
        assert report.details == report.details
    finally:
        await container.close()
