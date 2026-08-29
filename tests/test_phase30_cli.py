"""Phase 30 golden tests and completion gate.

A developer can operate and inspect the Brain without writing custom Python:
brainctl runtime, project, repository, context, work-item, execution, and
observation commands work through the same composition root and application
services.
"""

from __future__ import annotations

import uuid

import pytest
from typer.testing import CliRunner, Result

from brain.cli.commands import build_cli
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@localhost:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _invoke(runner: CliRunner, args: list[str]) -> Result:
    result = runner.invoke(build_cli(), args)
    assert result.exit_code == 0, f"command failed: {result.exception}\n{result.output}"
    return result


def test_help_lists_command_groups(runner: CliRunner) -> None:
    result = runner.invoke(build_cli(), ["--help"])
    assert result.exit_code == 0
    for name in (
        "status",
        "health",
        "capabilities",
        "project",
        "repository",
        "context",
        "work-item",
        "execution",
        "observation",
    ):
        assert name in result.output


def test_status_command(runner: CliRunner) -> None:
    result = _invoke(runner, ["status"])
    output = str(result.output)
    assert "environment" in output
    assert "ready" in output
    assert "executors" in output


def test_health_command(runner: CliRunner) -> None:
    result = _invoke(runner, ["health"])
    assert "ready" in str(result.output)


def test_capabilities_command(runner: CliRunner) -> None:
    result = _invoke(runner, ["capabilities"])
    output = str(result.output)
    assert "postgres" in output
    assert "neo4j" in output
    assert "work_management" in output


def test_project_crud_commands(runner: CliRunner) -> None:
    created = _invoke(runner, ["project", "create", "cli-test"])
    project_id = str(created.output).strip().split()[1]

    shown = _invoke(runner, ["project", "show", project_id])
    assert "cli-test" in str(shown.output)

    listed = _invoke(runner, ["project", "list"])
    assert "cli-test" in str(listed.output)


def test_work_item_and_context_commands(runner: CliRunner) -> None:
    created = _invoke(runner, ["project", "create", "cli-wi"])
    project_id = str(created.output).strip().split()[1]

    wi = _invoke(runner, ["work-item", "create", project_id, "Fix login"])
    work_item_id = str(wi.output).strip().split()[1]

    shown = _invoke(runner, ["work-item", "show", work_item_id])
    assert "Fix login" in str(shown.output)

    run = _invoke(runner, ["work-item", "run", work_item_id])
    assert "queued" in str(run.output)

    context = _invoke(runner, ["context", "build", work_item_id])
    assert "capsule" in str(context.output)


def test_context_explain_commands(runner: CliRunner) -> None:
    created = _invoke(runner, ["project", "create", "cli-ctx"])
    project_id = str(created.output).strip().split()[1]
    wi = _invoke(runner, ["work-item", "create", project_id, "Task"])
    work_item_id = str(wi.output).strip().split()[1]
    context = _invoke(runner, ["context", "build", work_item_id])
    capsule_id = str(context.output).strip().split()[1]

    shown = _invoke(runner, ["context", "show", capsule_id])
    assert "work item" in str(shown.output)

    explained = _invoke(runner, ["context", "explain", capsule_id])
    assert "primary task" in str(explained.output)


def test_repository_commands(runner: CliRunner) -> None:
    created = _invoke(runner, ["project", "create", "cli-repo"])
    project_id = str(created.output).strip().split()[1]

    added = _invoke(
        runner,
        ["repository", "add", project_id, "app", "git@example:app.git"],
    )
    repository_id = str(added.output).strip().split()[1]

    shown = _invoke(runner, ["repository", "status", repository_id])
    assert "app" in str(shown.output)

    synced = _invoke(runner, ["repository", "sync", repository_id])
    assert "queued" in str(synced.output)

    ingested = _invoke(runner, ["repository", "ingest", repository_id])
    assert "queued" in str(ingested.output)


def test_observation_commands(runner: CliRunner) -> None:
    created = _invoke(runner, ["project", "create", "cli-obs"])
    project_id = str(created.output).strip().split()[1]

    import asyncio

    from brain.application.observations import ObservationService
    from brain.cli.helpers import cli_container
    from brain.domain.identity import ProjectId
    from brain.domain.observations import ObservationType

    async def _seed() -> str:
        async with cli_container() as container:
            service = container.services["observations"]
            assert isinstance(service, ObservationService)
            observation = await service.create(
                project_id=ProjectId(uuid.UUID(project_id)),
                observation_type=ObservationType.DISCOVERY,
                title="Found partial implementation",
            )
            return str(observation.id)

    observation_id = asyncio.run(_seed())

    listed = _invoke(runner, ["observation", "list"])
    assert "Found partial implementation" in str(listed.output)

    shown = _invoke(runner, ["observation", "show", observation_id])
    assert "Found partial implementation" in str(shown.output)

    acknowledged = _invoke(runner, ["observation", "acknowledge", observation_id])
    assert "acknowledged" in str(acknowledged.output)

    resolved = _invoke(runner, ["observation", "resolve", observation_id])
    assert "resolved" in str(resolved.output)


def test_execution_show_command(runner: CliRunner) -> None:
    created = _invoke(runner, ["project", "create", "cli-exec"])
    project_id = str(created.output).strip().split()[1]
    wi = _invoke(runner, ["work-item", "create", project_id, "Task"])
    work_item_id = str(wi.output).strip().split()[1]

    import asyncio

    from brain.cli.helpers import cli_container
    from brain.domain.executions import Execution
    from brain.domain.identity import ActorId, WorkItemId, new_workflow_id

    async def _seed() -> str:
        async with cli_container() as container:
            work_item = await container.repositories.work_items.get(
                WorkItemId(uuid.UUID(work_item_id))
            )
            assert work_item is not None
            execution = Execution(
                workflow_id=new_workflow_id(),
                work_item_id=work_item.id,
                executor_id=ActorId(uuid.uuid4()),
            )
            created_exec = await container.repositories.executions.create(execution)
            return str(created_exec.id)

    execution_id = asyncio.run(_seed())
    shown = _invoke(runner, ["execution", "show", execution_id])
    assert "status" in str(shown.output)
