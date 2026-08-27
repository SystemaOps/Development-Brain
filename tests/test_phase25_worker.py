"""Phase 25 golden tests and completion gate.

FastAPI + Worker form an asynchronous Brain application: an API request
enqueues a command, the worker consumes it, the application service runs, and
state is updated — with failures persisted so the worker never crashes.
"""

from __future__ import annotations

import uuid

import pytest

from brain.adapters.in_memory.commands import InMemoryCommandQueue
from brain.api.app import create_app
from brain.application.command_dispatcher import CommandDispatcher
from brain.application.command_handlers import install_command_handlers
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
from brain.domain.command_failure import CommandFailureCategory
from brain.domain.commands import (
    CommandType,
    RunWorkItemCommand,
    make_command,
)
from brain.domain.identity import WorkItemId
from brain.workers.loop import WorkerLoop, classify_failure, process_command
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


def test_failure_classification() -> None:
    category, retry = classify_failure(ValueError("invalid input: nope"))
    assert category == CommandFailureCategory.INVALID_INPUT
    assert retry is False

    category, retry = classify_failure(RuntimeError("verification failed"))
    assert category == CommandFailureCategory.VERIFICATION_FAILURE
    assert retry is True

    category, retry = classify_failure(RuntimeError("something broke"))
    assert category == CommandFailureCategory.INTERNAL
    assert retry is True


async def test_process_command_persists_failure_and_reraises() -> None:
    from brain.adapters.in_memory.command_failure import InMemoryCommandFailureRepository

    failures = InMemoryCommandFailureRepository()
    dispatcher = CommandDispatcher()

    async def broken_handler(command: object) -> object:
        del command
        raise RuntimeError("verification failed for execution")

    dispatcher.register(CommandType.VERIFY_EXECUTION, broken_handler)
    from brain.domain.commands import VerifyExecutionCommand
    from brain.domain.identity import ExecutionId

    envelope = make_command(
        CommandType.VERIFY_EXECUTION,
        VerifyExecutionCommand(
            execution_id=ExecutionId(uuid.uuid4()),
            work_item_id=WorkItemId(uuid.uuid4()),
        ),
    )

    with pytest.raises(RuntimeError):
        await process_command(dispatcher=dispatcher, failures=failures, command=envelope)
    recorded = await failures.list_by_command(envelope.command_id)
    assert len(recorded) == 1
    assert recorded[0].category == CommandFailureCategory.VERIFICATION_FAILURE
    assert recorded[0].retry_eligible is True
    assert recorded[0].correlation_id == envelope.correlation_id


async def test_worker_loop_acknowledges_success() -> None:
    container = await create_brain_container(_settings())
    try:
        queue = container.services["command_queue"]
        assert isinstance(queue, InMemoryCommandQueue)
        dispatcher: CommandDispatcher = install_command_handlers(container=container)
        loop = WorkerLoop(container=container, dispatcher=dispatcher, queue=queue)

        # Seed a project + work item so the RunWorkItemCommand succeeds.
        from brain.domain.projects import Project
        from brain.domain.work_items import WorkItem

        project = Project(name="worker-demo")
        await container.repositories.projects.create(project)
        work_item = WorkItem(project_id=project.id, title="Task")
        await container.repositories.work_items.create(work_item)

        await queue.enqueue(
            make_command(
                CommandType.RUN_WORK_ITEM,
                RunWorkItemCommand(work_item_id=work_item.id),
            )
        )
        processed = await loop.run(max_commands=1)
        assert processed == 1
        assert await queue.pending_count() == 0
    finally:
        await container.close()


async def test_worker_loop_dead_letters_failed_command() -> None:
    container = await create_brain_container(_settings())
    try:
        queue = container.services["command_queue"]
        assert isinstance(queue, InMemoryCommandQueue)
        dispatcher = container.services["command_dispatcher"]
        assert isinstance(dispatcher, CommandDispatcher)

        async def broken_handler(envelope: object) -> object:
            del envelope
            raise RuntimeError("boom")

        dispatcher.register(CommandType.RUN_WORK_ITEM, broken_handler)
        loop = WorkerLoop(container=container, dispatcher=dispatcher, queue=queue)
        await queue.enqueue(
            make_command(
                CommandType.RUN_WORK_ITEM,
                RunWorkItemCommand(work_item_id=WorkItemId(uuid.uuid4())),
            )
        )
        processed = await loop.run(max_commands=1)
        assert processed == 1
        assert len(queue.dead_letters()) == 1
        # Failure persisted once per attempt and the worker survived.
        failures = await container.repositories.command_failures.list_recent()
        assert len(failures) >= 1
    finally:
        await container.close()


async def test_gate_api_to_queue_to_worker_to_state() -> None:
    """End-to-end: API request -> command queued -> worker consumes ->
    application service invoked -> state updated (single event loop)."""
    import httpx

    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        # API creates a project and a work item, then queues a run command.
        project_response = await client.post("/api/v1/projects", json={"name": "e2e"})
        assert project_response.status_code == 201
        project = project_response.json()
        work_item_response = await client.post(
            "/api/v1/work-items",
            json={"project_id": project["id"], "title": "E2E task"},
        )
        work_item = work_item_response.json()
        run_response = await client.post(f"/api/v1/work-items/{work_item['id']}/run")
        assert run_response.status_code == 202
        assert uuid.UUID(run_response.json()["command_id"])

        # The worker consumes the queued command in the same loop.
        container = app.state.container
        queue = container.services["command_queue"]
        assert isinstance(queue, InMemoryCommandQueue)
        dispatcher: CommandDispatcher = install_command_handlers(container=container)
        loop = WorkerLoop(container=container, dispatcher=dispatcher, queue=queue)
        processed = await loop.run(max_commands=1)
        assert processed == 1

        # The run command succeeded end-to-end; no failures recorded.
        failures = await container.repositories.command_failures.list_recent()
        assert not failures
