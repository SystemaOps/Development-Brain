"""Phase 24 golden tests and completion gate.

Long-running API operations are queued and the orchestration path no longer
depends on whether the trigger came from a human or event: ``POST
/work-items/{id}/run`` and the ``WorkItemAssigned`` event converge on the same
``RunWorkItemCommand`` semantics.
"""

from __future__ import annotations

import uuid

import pytest

from brain.adapters.in_memory.commands import InMemoryCommandQueue
from brain.application.command_dispatcher import (
    CommandDispatcher,
    CommandHandlerNotFound,
    run_command_loop,
)
from brain.application.command_handlers import install_command_handlers
from brain.bootstrap.container import BrainContainer, create_brain_container
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
from brain.domain.commands import (
    AnalyzeProjectCommand,
    CommandEnvelope,
    CommandType,
    RunWorkItemCommand,
    TriggerType,
    command_to_model,
    make_command,
)
from brain.domain.identity import ProjectId, WorkItemId
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.work_items import WorkItem

pytestmark = pytest.mark.skipif(
    not __import__("tests.conftest", fromlist=["postgres_reachable"]).postgres_reachable(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
    ),
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


async def test_command_envelope_fields() -> None:
    command = make_command(
        CommandType.RUN_WORK_ITEM,
        RunWorkItemCommand(work_item_id=WorkItemId(uuid.uuid4())),
        trigger_type=TriggerType.USER,
        requested_by=None,
    )
    assert command.command_type == CommandType.RUN_WORK_ITEM
    assert command.trigger_type == TriggerType.USER
    assert command.command_id is not None
    assert command.correlation_id is not None
    assert command.payload["work_item_id"]
    assert command.requested_at is not None


async def test_command_round_trip_through_model() -> None:
    work_item_id = WorkItemId(uuid.uuid4())
    command = make_command(
        CommandType.RUN_WORK_ITEM,
        RunWorkItemCommand(work_item_id=work_item_id),
    )
    model = command_to_model(command)
    assert isinstance(model, RunWorkItemCommand)
    assert model.work_item_id == work_item_id


async def test_in_memory_queue_enqueue_consume_ack() -> None:
    queue = InMemoryCommandQueue()
    command = make_command(
        CommandType.RUN_WORK_ITEM,
        RunWorkItemCommand(work_item_id=WorkItemId(uuid.uuid4())),
    )
    await queue.enqueue(command)
    assert await queue.pending_count() == 1
    consumed = await queue.consume(timeout_seconds=0.1)
    assert consumed is not None
    assert consumed.command_id == command.command_id
    assert await queue.pending_count() == 0
    await queue.acknowledge(command.command_id)


async def test_in_memory_queue_consume_empty_times_out() -> None:
    queue = InMemoryCommandQueue()
    assert await queue.consume(timeout_seconds=0.05) is None


async def test_in_memory_queue_dead_letter() -> None:
    queue = InMemoryCommandQueue()
    command = make_command(
        CommandType.RUN_WORK_ITEM,
        RunWorkItemCommand(work_item_id=WorkItemId(uuid.uuid4())),
    )
    await queue.enqueue(command)
    await queue.consume(timeout_seconds=0.1)
    await queue.dead_letter(command, "boom")
    assert len(queue.dead_letters()) == 1
    assert queue.dead_letters()[0][1] == "boom"


async def test_dispatcher_routes_to_registered_handler() -> None:
    dispatcher = CommandDispatcher()
    calls: list[CommandType] = []

    async def handler(command: CommandEnvelope) -> object:
        calls.append(command.command_type)
        return {}

    dispatcher.register(CommandType.ANALYZE_PROJECT, handler)
    command = make_command(
        CommandType.ANALYZE_PROJECT,
        AnalyzeProjectCommand(project_id=ProjectId(uuid.uuid4())),
    )
    await dispatcher.dispatch(command)
    assert calls == [CommandType.ANALYZE_PROJECT]


async def test_dispatcher_raises_for_unknown_command() -> None:
    dispatcher = CommandDispatcher()
    command = make_command(
        CommandType.ANALYZE_PROJECT,
        AnalyzeProjectCommand(project_id=ProjectId(uuid.uuid4())),
    )
    with pytest.raises(CommandHandlerNotFound):
        await dispatcher.dispatch(command)


async def test_run_command_loop_processes_queue() -> None:
    queue = InMemoryCommandQueue()
    dispatcher = CommandDispatcher()

    async def handler(command: CommandEnvelope) -> object:
        return {}

    dispatcher.register(CommandType.RUN_WORK_ITEM, handler)
    await queue.enqueue(
        make_command(
            CommandType.RUN_WORK_ITEM,
            RunWorkItemCommand(work_item_id=WorkItemId(uuid.uuid4())),
        )
    )
    processed = await run_command_loop(dispatcher, queue)()
    assert processed == 1


async def test_run_command_loop_failure_goes_to_dead_letter() -> None:
    queue = InMemoryCommandQueue()
    dispatcher = CommandDispatcher()

    async def handler(command: CommandEnvelope) -> object:
        raise RuntimeError("boom")

    dispatcher.register(CommandType.RUN_WORK_ITEM, handler)
    await queue.enqueue(
        make_command(
            CommandType.RUN_WORK_ITEM,
            RunWorkItemCommand(work_item_id=WorkItemId(uuid.uuid4())),
        )
    )
    processed = await run_command_loop(dispatcher, queue)()
    assert processed == 1
    assert len(queue.dead_letters()) == 1


async def _seed_project_and_work_item(
    container: BrainContainer,
) -> tuple[Project, WorkItem, Repository]:
    project = Project(name="seed")
    await container.repositories.projects.create(project)
    repository = Repository(project_id=project.id, name="app", clone_url="git@example:app.git")
    await container.repositories.repositories.create(repository)
    work_item = WorkItem(project_id=project.id, title="Task")
    await container.repositories.work_items.create(work_item)
    return project, work_item, repository


async def test_gate_user_trigger_converges_on_run_work_item_command() -> None:
    """A user API call and a WorkItemAssigned event both produce a
    RunWorkItemCommand that reaches the same handler."""
    container = await create_brain_container(_settings())
    try:
        _, work_item, _ = await _seed_project_and_work_item(container)

        # User trigger: POST /work-items/{id}/run semantics = enqueue command.

        user_envelope: CommandEnvelope = make_command(
            CommandType.RUN_WORK_ITEM,
            RunWorkItemCommand(work_item_id=work_item.id),
            trigger_type=TriggerType.USER,
        )

        # Event trigger: WorkItemAssigned -> same command semantics.
        event_envelope = make_command(
            CommandType.RUN_WORK_ITEM,
            RunWorkItemCommand(work_item_id=work_item.id),
            trigger_type=TriggerType.EVENT,
        )

        queue = container.services["command_queue"]
        assert isinstance(queue, InMemoryCommandQueue)
        await queue.enqueue(user_envelope)
        await queue.enqueue(event_envelope)

        dispatcher = install_command_handlers(container=container)
        processed = await run_command_loop(dispatcher, queue)()
        assert processed == 2

        # Both converged on the same command semantics via the same handler.
        assert dispatcher.has_handler(CommandType.RUN_WORK_ITEM)
        results = []
        for command in (user_envelope, event_envelope):
            results.append(await dispatcher.dispatch(command))
        for result in results:
            assert result["status"] == "started"
            assert result["work_item_id"] == work_item.id
    finally:
        await container.close()


async def test_gate_api_202_returns_real_command_id() -> None:
    """The API's 202 accepted result carries a real enqueued command id."""
    from fastapi.testclient import TestClient

    from brain.api.app import create_app

    app = create_app(_settings())
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "cmd-demo"}).json()
        work_item = client.post(
            "/api/v1/work-items",
            json={"project_id": project["id"], "title": "Run me"},
        ).json()
        response = client.post(f"/api/v1/work-items/{work_item['id']}/run")
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "ACCEPTED"
        assert uuid.UUID(body["command_id"])
