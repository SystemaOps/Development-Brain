from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent_core.domain.coding import (
    CodingAttemptRequest,
    CodingAttemptResult,
    FileChange,
    RollbackPlan,
)
from agent_core.domain.enums import (
    CodingAttemptStatus,
    PlanNodeKind,
    PlanVersionStatus,
)
from agent_core.models import (
    ContextCapsule,
    PlanNode,
    PlanNodeIdentity,
    PlanVersion,
    Project,
)
from agent_core.persistence.agent_transition_context import (
    SqlAlchemyAgentTransitionContextStore,
)
from agent_core.persistence.coding_attempts import (
    SqlAlchemyCodingAttemptStore,
)


POSTGRES_URL_ENV = "PHASE3_POSTGRES_DATABASE_URL"


@pytest.fixture(scope="module")
def migrated_postgres_url() -> str:
    database_url = os.getenv(POSTGRES_URL_ENV)
    if not database_url:
        pytest.skip(
            f"Set {POSTGRES_URL_ENV} to run live transition-context integration tests"
        )

    repo_root = Path(__file__).resolve().parents[1]
    package_root = repo_root / "agent_core"
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=package_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return database_url


@pytest.mark.asyncio
async def test_transition_context_loads_persisted_task_and_coding_data(
    migrated_postgres_url: str,
):
    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            project = Project(
                project_key=f"transition-context-{uuid4()}",
                name="Transition Context",
            )
            session.add(project)
            await session.flush()
            version = PlanVersion(
                project_id=project.id,
                version_number=1,
                status=PlanVersionStatus.APPROVED.value,
                generated_from="integration_test",
                plan_json={},
            )
            identity = PlanNodeIdentity(
                project_id=project.id,
                stable_key="task.transition-context",
                kind=PlanNodeKind.TASK.value,
            )
            session.add_all([version, identity])
            await session.flush()
            node = PlanNode(
                project_id=project.id,
                plan_version_id=version.id,
                node_identity_id=identity.id,
                kind=PlanNodeKind.TASK.value,
                title="Load transition context",
                objective="Load task data for the next agent.",
                node_json={
                    "acceptance_criteria": [
                        {
                            "key": "ac.transition-context",
                            "statement": "Transition context is loaded.",
                            "verification_method": "integration_test",
                        }
                    ]
                },
            )
            session.add(node)
            await session.flush()
            identity.current_plan_node_id = node.id
            prepared_attempt = CodingAttemptRequest(
                task_key=identity.stable_key,
                repository_key="sample-project",
                file_changes=[
                    FileChange(
                        relative_path="src/app.py",
                        content="TRANSITION_CONTEXT = True\n",
                    )
                ],
            )
            session.add(
                ContextCapsule(
                    project_id=project.id,
                    plan_version_id=version.id,
                    plan_node_id=node.id,
                    capsule_type="execution",
                    content="Task execution context.",
                    capsule_json={
                        "prepared_coding_attempt": prepared_attempt.model_dump(
                            mode="json"
                        )
                    },
                    source_refs=[{"type": "plan_node", "id": str(node.id)}],
                )
            )
            await session.commit()

            coding_result = CodingAttemptResult(
                task_key=identity.stable_key,
                repository_key="sample-project",
                attempt_number=1,
                status=CodingAttemptStatus.SUCCEEDED,
                changed_files=["src/app.py"],
                final_diff="+TRANSITION_CONTEXT = True",
                rollback_plan=RollbackPlan(
                    available=True,
                    strategy="reverse_diff",
                    changed_files=["src/app.py"],
                ),
            )
            await SqlAlchemyCodingAttemptStore(session).record_result(
                project_id=project.id,
                result=coding_result,
            )

            context = await SqlAlchemyAgentTransitionContextStore(
                session
            ).load_task_context(
                project_id=project.project_key,
                task_id=identity.stable_key,
                workflow_id="workflow-transition-context",
                plan_version_id=str(version.id),
            )

            assert context is not None
            assert context.task_id == identity.stable_key
            assert context.planning_approved is True
            assert context.prepared_coding_attempt == prepared_attempt
            assert context.latest_coding_result == coding_result
            assert context.acceptance_criteria[0].key == "ac.transition-context"
            assert context.input_artifacts[0].artifact_type == "context_capsule"
    finally:
        await engine.dispose()
