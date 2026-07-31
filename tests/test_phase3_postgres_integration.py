from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent_core.domain.enums import (
    ApprovalDecision,
    ApprovalScope,
    RepositoryAccessMode,
)
from agent_core.domain.events import EventEnvelope
from agent_core.domain.repositories import RepositoryBinding
from agent_core.models import (
    AgentJob,
    AgentPlatformCheckpointRecord,
    AgentPlatformFlowRecord,
    AgentPlatformResultRecord,
    ApprovalRecord,
    CodingAttemptRecord,
    ExternalArtifact,
    Project,
    RepositoryBindingRecord,
    RepositoryRelationshipRecord,
    RepositorySymbolRecord,
    WebhookEvent,
)
from agent_core.persistence.approvals import SqlAlchemyApprovalRecordStore
from agent_core.persistence.openproject_artifacts import (
    SqlAlchemyOpenProjectArtifactStore,
)
from agent_core.persistence.event_inbox import SqlAlchemyEventInbox
from agent_core.persistence.repository_bindings import (
    SqlAlchemyRepositoryBindingStore,
)
from agent_core.persistence.repository_index import SqlAlchemyRepositoryIndexStore
from agent_core.ports.approvals import ApprovalRecordInput
from agent_core.services.repository_analysis_service import RepositoryAnalysisService


POSTGRES_URL_ENV = "PHASE3_POSTGRES_DATABASE_URL"


@pytest.fixture(scope="module")
def postgres_database_url() -> str:
    database_url = os.getenv(POSTGRES_URL_ENV)
    if not database_url:
        pytest.skip(f"Set {POSTGRES_URL_ENV} to run live Postgres Phase 3 integration tests")
    return database_url


@pytest.fixture(scope="module")
def migrated_postgres_url(postgres_database_url: str) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    package_root = repo_root / "agent_core"
    env = os.environ.copy()
    env["DATABASE_URL"] = postgres_database_url

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=package_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return postgres_database_url


def test_phase3_alembic_upgrade_creates_expected_tables(migrated_postgres_url: str):
    with psycopg.connect(_to_psycopg_url(migrated_postgres_url)) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version")
            assert cur.fetchone()[0] == "0014_queued_agent_flows"

            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN (
                      'pm_webhook_events',
                      'agent_jobs',
                      'agent_platform_checkpoints',
                      'agent_platform_flows',
                      'agent_platform_results',
                      'agent_executions',
                      'approval_records',
                      'coding_attempts',
                      'openproject_outbound_operations',
                      'openproject_reconciliation_snapshots',
                      'pm_context_snapshots',
                      'repository_bindings',
                      'repository_relationships',
                      'repository_symbols'
                  )
                ORDER BY table_name
                """
            )
            assert [row[0] for row in cur.fetchall()] == [
                "agent_executions",
                "agent_jobs",
                "agent_platform_checkpoints",
                "agent_platform_flows",
                "agent_platform_results",
                "approval_records",
                "coding_attempts",
                "openproject_outbound_operations",
                "openproject_reconciliation_snapshots",
                "pm_context_snapshots",
                "pm_webhook_events",
                "repository_bindings",
                "repository_relationships",
                "repository_symbols",
            ]

            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'agent_executions'
                """
            )
            execution_columns = {row[0] for row in cur.fetchall()}
            assert {
                "project_id",
                "agent_name",
                "thread_id",
                "trigger_event_id",
                "attempt_number",
                "status",
                "config_snapshot",
                "error_summary",
            } <= execution_columns

            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'agent_platform_flows'
                """
            )
            flow_columns = {row[0] for row in cur.fetchall()}
            assert {
                "recovery_count",
                "lease_id",
                "lease_owner",
                "lease_acquired_at",
                "lease_expires_at",
            } <= flow_columns

            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename = 'agent_platform_flows'
                """
            )
            assert "idx_agent_platform_flows_claimable" in {
                row[0] for row in cur.fetchall()
            }

            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'coding_attempts'
                """
            )
            coding_attempt_columns = {row[0] for row in cur.fetchall()}
            assert {
                "project_id",
                "repository_key",
                "task_key",
                "attempt_number",
                "status",
                "changed_files",
                "command_results",
                "rollback_plan",
                "final_diff",
                "error_summary",
            } <= coding_attempt_columns


@pytest.mark.asyncio
async def test_phase3_event_inbox_duplicate_delivery_creates_one_job(
    migrated_postgres_url: str,
):
    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    delivery_id = str(uuid4())
    envelope = EventEnvelope(
        source="openproject",
        event_type="work_package.updated",
        external_project_id="12",
        external_work_package_id="34",
        payload={"action": "work_package.updated", "delivery_id": delivery_id},
        headers={"x-request-id": delivery_id},
    )

    try:
        async with session_factory() as session:
            inbox = SqlAlchemyEventInbox(session)
            first = await inbox.persist(envelope)
            second = await inbox.persist(envelope)

            assert first.created is True
            assert second.created is False
            assert second.event_id == first.event_id

            event_count = await session.scalar(
                select(WebhookEvent).where(
                    WebhookEvent.idempotency_key == envelope.idempotency_key
                )
            )
            assert event_count is not None

            jobs = await session.scalars(
                select(AgentJob).where(AgentJob.event_id == event_count.id)
            )
            assert len(list(jobs)) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_phase4_openproject_artifact_mapping_upsert_is_idempotent(
    migrated_postgres_url: str,
):
    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    external_id = f"wp-{uuid4()}"

    try:
        async with session_factory() as session:
            project = Project(
                project_key=f"phase4-artifacts-{uuid4()}",
                name="Phase 4 Artifact Mapping",
            )
            session.add(project)
            await session.commit()
            await session.refresh(project)

            store = SqlAlchemyOpenProjectArtifactStore(session)
            first = await store.upsert_mapping(
                project_id=project.id,
                artifact_type="work_package",
                external_id=external_id,
                external_url=f"/api/v3/work_packages/{external_id}",
                external_payload={"subject": "First"},
            )
            second = await store.upsert_mapping(
                project_id=project.id,
                artifact_type="work_package",
                external_id=external_id,
                external_url=f"/api/v3/work_packages/{external_id}",
                external_payload={"subject": "Second"},
            )

            assert second.artifact_id == first.artifact_id
            artifact = await session.scalar(
                select(ExternalArtifact).where(ExternalArtifact.id == first.artifact_id)
            )
            assert artifact is not None
            assert artifact.external_payload == {"subject": "Second"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_phase4_approval_record_source_decision_is_idempotent(
    migrated_postgres_url: str,
):
    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    source_event_id = f"approval-{uuid4()}"

    try:
        async with session_factory() as session:
            project = Project(
                project_key=f"phase4-approvals-{uuid4()}",
                name="Phase 4 Approval Record",
            )
            session.add(project)
            await session.commit()
            await session.refresh(project)

            store = SqlAlchemyApprovalRecordStore(session)
            first = await store.record(
                ApprovalRecordInput(
                    project_id=project.id,
                    approval_scope=ApprovalScope.PLANNING,
                    decision=ApprovalDecision.APPROVED,
                    source_event_id=source_event_id,
                    payload={"comment": {"raw": "Approved."}},
                )
            )
            second = await store.record(
                ApprovalRecordInput(
                    project_id=project.id,
                    approval_scope=ApprovalScope.PLANNING,
                    decision=ApprovalDecision.APPROVED,
                    source_event_id=source_event_id,
                    payload={"comment": {"raw": "Approved."}},
                )
            )

            assert second.approval_id == first.approval_id
            approvals = await session.scalars(
                select(ApprovalRecord).where(
                    ApprovalRecord.source_event_id == source_event_id
                )
            )
            assert len(list(approvals)) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_phase5_repository_binding_upsert_is_idempotent(
    migrated_postgres_url: str,
):
    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            project = Project(
                project_key=f"phase5-repositories-{uuid4()}",
                name="Phase 5 Repository Binding",
            )
            session.add(project)
            await session.commit()
            await session.refresh(project)

            store = SqlAlchemyRepositoryBindingStore(session)
            first = await store.upsert_binding(
                project_id=project.id,
                binding=RepositoryBinding(
                    repository_key="sample-project",
                    mount_path="/workspace/repositories/sample_project",
                    access_mode=RepositoryAccessMode.READ_ONLY,
                    command_allowlist=("pytest",),
                ),
            )
            second = await store.upsert_binding(
                project_id=project.id,
                binding=RepositoryBinding(
                    repository_key="sample-project",
                    mount_path="/workspace/repositories/sample_project",
                    access_mode=RepositoryAccessMode.READ_WRITE,
                    write_allowlist=("src/**", "tests/**"),
                    command_allowlist=("pytest", "python"),
                ),
            )

            assert first.repository_key == second.repository_key == "sample-project"
            record = await session.scalar(
                select(RepositoryBindingRecord).where(
                    RepositoryBindingRecord.project_id == project.id,
                    RepositoryBindingRecord.repository_key == "sample-project",
                )
            )
            assert record is not None
            assert record.access_mode == RepositoryAccessMode.READ_WRITE.value
            assert record.write_allowlist == ["src/**", "tests/**"]

            loaded = await store.get_binding(
                project_id=project.id,
                repository_key="sample-project",
            )
            assert loaded == second
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_phase5_repository_index_replace_is_queryable(
    migrated_postgres_url: str,
):
    from agent_core.adapters.repository_analysis import PythonAstRepositoryAnalyzer

    repo_root = Path(__file__).resolve().parents[1]
    sample_project = repo_root / "sample_project"
    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            project = Project(
                project_key=f"phase5-index-{uuid4()}",
                name="Phase 5 Repository Index",
            )
            session.add(project)
            await session.commit()
            await session.refresh(project)

            index = await PythonAstRepositoryAnalyzer(
                [
                    RepositoryBinding(
                        repository_key="sample-project",
                        mount_path=str(sample_project),
                    )
                ]
            ).index_repository(repository_key="sample-project")

            store = SqlAlchemyRepositoryIndexStore(session)
            await store.replace_index(project_id=project.id, index=index)
            await store.replace_index(project_id=project.id, index=index)

            symbols = await store.list_symbols(
                project_id=project.id,
                repository_key="sample-project",
            )
            relationships = await store.list_relationships(
                project_id=project.id,
                repository_key="sample-project",
            )

            assert {symbol.name for symbol in symbols} >= {
                "main.py",
                "calculate_total",
                "checkout",
                "services.payment.PaymentService",
            }
            assert any(
                relationship.relationship_type.value == "calls"
                and relationship.target_name == "calculate_total"
                for relationship in relationships
            )

            symbol_records = await session.scalars(
                select(RepositorySymbolRecord).where(
                    RepositorySymbolRecord.project_id == project.id,
                    RepositorySymbolRecord.repository_key == "sample-project",
                )
            )
            relationship_records = await session.scalars(
                select(RepositoryRelationshipRecord).where(
                    RepositoryRelationshipRecord.project_id == project.id,
                    RepositoryRelationshipRecord.repository_key == "sample-project",
                )
            )
            assert len(list(symbol_records)) == len(index.symbols)
            assert len(list(relationship_records)) == len(index.relationships)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_phase5_repository_analysis_service_binds_and_indexes_sample_project(
    migrated_postgres_url: str,
):
    repo_root = Path(__file__).resolve().parents[1]
    sample_project = repo_root / "sample_project"
    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            project = Project(
                project_key=f"phase5-service-{uuid4()}",
                name="Phase 5 Repository Service",
            )
            session.add(project)
            await session.commit()

            service = RepositoryAnalysisService(
                session,
                repository_mount_root=str(repo_root),
            )
            binding = await service.bind_repository(
                project_key=project.project_key,
                binding=RepositoryBinding(
                    repository_key="sample-project",
                    mount_path=str(sample_project),
                ),
            )
            summary = await service.index_repository(
                project_key=project.project_key,
                repository_key=binding.repository_key,
            )
            symbols = await service.list_symbols(
                project_key=project.project_key,
                repository_key=binding.repository_key,
            )

            assert summary.symbol_count >= 4
            assert summary.relationship_count >= 3
            assert {symbol.name for symbol in symbols} >= {"calculate_total", "checkout"}
            assert any("LSP analysis is unavailable" in warning for warning in summary.warnings)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_platform_postgres_checkpoint_and_result_stores(
    migrated_postgres_url: str,
):
    from agent_core.agent_platform.agents.base import (
        AgentNextAction,
        AgentResult,
        AgentRunStatus,
    )
    from agent_core.agent_platform.runtime import CheckpointIdentity
    from agent_core.persistence.agent_platform import (
        SqlAlchemyAgentCheckpointStore,
        SqlAlchemyAgentResultStore,
    )

    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            project_key = f"platform-{uuid4()}"
            execution_id = uuid4()
            identity = CheckpointIdentity(
                project_id=project_key,
                workflow_id="workflow-platform-test",
                agent_type="planning",
                agent_instance_id="planning:default",
                execution_id=execution_id,
                thread_id=f"{project_key}:task.platform:planning",
                checkpoint_id="checkpoint-1",
            )
            checkpoint_store = SqlAlchemyAgentCheckpointStore(session)
            result_store = SqlAlchemyAgentResultStore(session)

            assert await checkpoint_store.load(identity=identity) is None
            assert await checkpoint_store.save(identity=identity, state={"phase": "created"}) == "checkpoint-1"
            assert await checkpoint_store.save(identity=identity, state={"phase": "completed"}) == "checkpoint-1"
            assert await checkpoint_store.load(identity=identity) == {"phase": "completed"}

            persisted = await result_store.persist(
                AgentResult(
                    execution_id=execution_id,
                    project_id=project_key,
                    task_id="task.platform",
                    agent_type="planning",
                    status=AgentRunStatus.SUCCEEDED,
                    summary="Planning completed.",
                    next_action=AgentNextAction.RUN_CODING,
                )
            )
            payload = await result_store.get_payload(persisted.result_id)

            checkpoint_records = await session.scalars(
                select(AgentPlatformCheckpointRecord).where(
                    AgentPlatformCheckpointRecord.execution_id == execution_id
                )
            )
            result_record = await session.scalar(
                select(AgentPlatformResultRecord).where(
                    AgentPlatformResultRecord.id == persisted.result_id
                )
            )

            assert len(list(checkpoint_records)) == 1
            assert result_record is not None
            assert result_record.project_key == project_key
            assert result_record.task_key == "task.platform"
            assert result_record.status == AgentRunStatus.SUCCEEDED.value
            assert payload is not None
            assert payload["next_action"] == AgentNextAction.RUN_CODING.value
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_verification_override_audit_survives_flow_store_recreation(
    migrated_postgres_url: str,
):
    from agent_core.agent_platform.agents.verification import (
        VerificationAgentRequest,
        VerificationOverrideCommand,
        VerificationVerdict,
    )
    from agent_core.agent_platform.config import AgentConfig
    from agent_core.agent_platform.orchestration import (
        AgentExecutionRequest,
        AgentFlowStatus,
    )
    from agent_core.agent_platform.runtime import AgentDependencyContainer
    from agent_core.domain.coding import CodingAttemptResult, RollbackPlan
    from agent_core.domain.enums import CodingAttemptStatus
    from agent_core.persistence.agent_flows import SqlAlchemyAgentFlowStore
    from agent_core.schemas import AcceptanceCriterionSpec
    from agent_core.services.agent_platform_service import (
        create_agent_platform_service,
    )

    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    flow_id = None

    try:
        async with session_factory() as session:
            workflow_id = f"verification-override-{uuid4()}"
            service = create_agent_platform_service(
                AgentDependencyContainer(),
                flow_store=SqlAlchemyAgentFlowStore(session),
            )
            execution = AgentExecutionRequest(
                workflow_id=workflow_id,
                agent_type="verification",
                request=VerificationAgentRequest(
                    project_id=f"override-project-{uuid4()}",
                    task_id="task.verification-override",
                    objective="Verify durable override auditing.",
                    acceptance_criteria=[
                        AcceptanceCriterionSpec(
                            key="ac.durable-override",
                            statement="Override audit survives store recreation.",
                            verification_method="integration_test",
                        )
                    ],
                    coding_result=CodingAttemptResult(
                        task_key="task.verification-override",
                        repository_key="demo",
                        attempt_number=1,
                        status=CodingAttemptStatus.SUCCEEDED,
                        changed_files=["src/feature.py"],
                        final_diff="+unrelated implementation detail\n",
                        rollback_plan=RollbackPlan(
                            available=True,
                            strategy="reverse_diff",
                            changed_files=["src/feature.py"],
                        ),
                    ),
                ),
                config=AgentConfig(
                    agent_type="verification",
                    checkpoint_namespace="verification",
                    settings={
                        "human_override_enabled": True,
                        "human_override_allowed_verdicts": ["changes_requested"],
                    },
                ),
            )
            waiting = await service.start_flow(execution)
            completed = await service.override_verification_flow(
                flow_id=waiting.flow_id,
                expected_version=waiting.version,
                command=VerificationOverrideCommand(
                    actor="postgres-reviewer",
                    reason="Approved through durable change control.",
                    override_reference=f"postgres-override-{uuid4()}",
                ),
            )
            flow_id = completed.flow_id

            assert waiting.status == AgentFlowStatus.WAITING_FOR_APPROVAL
            assert completed.status == AgentFlowStatus.COMPLETED
            assert completed.overrides[0].original_outcome == (
                VerificationVerdict.CHANGES_REQUESTED.value
            )

        async with session_factory() as recreated_session:
            reloaded = await SqlAlchemyAgentFlowStore(recreated_session).get(flow_id)
            record = await recreated_session.get(AgentPlatformFlowRecord, flow_id)

            assert reloaded is not None
            assert reloaded.status == AgentFlowStatus.COMPLETED
            assert reloaded.overrides[0].actor == "postgres-reviewer"
            assert reloaded.overrides[0].finding_codes == ["acceptance_criterion_unmet"]
            assert record is not None
            assert record.flow_json["overrides"][0]["source_agent_type"] == (
                "verification"
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_phase7_coding_attempt_store_persists_attempt_result(
    migrated_postgres_url: str,
):
    from agent_core.domain.coding import CodingAttemptResult, RollbackPlan
    from agent_core.domain.enums import CodingAttemptStatus
    from agent_core.persistence.coding_attempts import SqlAlchemyCodingAttemptStore

    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            project = Project(
                project_key=f"phase7-coding-{uuid4()}",
                name="Phase 7 Coding Attempt",
            )
            session.add(project)
            await session.commit()
            await session.refresh(project)

            store = SqlAlchemyCodingAttemptStore(session)
            attempt_number = await store.next_attempt_number(
                project_id=project.id,
                repository_key="sample-project",
                task_key="task.sample",
            )
            assert attempt_number == 1

            attempt_id = await store.record_result(
                project_id=project.id,
                result=CodingAttemptResult(
                    task_key="task.sample",
                    repository_key="sample-project",
                    attempt_number=attempt_number,
                    status=CodingAttemptStatus.SUCCEEDED,
                    changed_files=["src/app.py"],
                    final_diff="diff --git a/src/app.py b/src/app.py",
                    rollback_plan=RollbackPlan(
                        available=True,
                        strategy="reverse_diff",
                        changed_files=["src/app.py"],
                        reverse_diff="diff --git a/src/app.py b/src/app.py",
                    ),
                ),
            )

            record = await session.scalar(
                select(CodingAttemptRecord).where(CodingAttemptRecord.id == attempt_id)
            )
            assert record is not None
            assert record.status == CodingAttemptStatus.SUCCEEDED.value
            assert record.changed_files == ["src/app.py"]
            assert record.rollback_plan["strategy"] == "reverse_diff"
            assert (
                await store.next_attempt_number(
                    project_id=project.id,
                    repository_key="sample-project",
                    task_key="task.sample",
                )
            ) == 2
    finally:
        await engine.dispose()


def _to_psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
