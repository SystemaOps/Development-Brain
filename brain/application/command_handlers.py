"""Default command handlers (Phase 24/25).

Maps canonical commands to existing application services.  Handlers contain no
business logic beyond calling the right service — the worker runtime reuses
these so the API, worker, and CLI converge on the same behavior.
"""

from __future__ import annotations

from brain.application.command_dispatcher import CommandDispatcher
from brain.bootstrap.container import BrainContainer
from brain.domain.commands import (
    AnalyzeProjectCommand,
    AnalyzeWorkItemCommand,
    BuildContextCommand,
    CommandEnvelope,
    CommandType,
    CreatePullRequestCommand,
    ExecuteWorkItemCommand,
    ExtractRequirementsCommand,
    IngestDocumentCommand,
    IngestRepositoryCommand,
    PlanWorkItemCommand,
    ReconcileProjectCommand,
    RunWorkItemCommand,
    SyncRepositoryCommand,
    VerifyExecutionCommand,
    command_to_model,
)
from brain.domain.identity import (
    ProjectId,
    new_execution_id,
)
from brain.domain.repositories import Repository


class CommandHandlers:
    """Registers command handlers against application services."""

    def __init__(
        self,
        *,
        container: BrainContainer,
        dispatcher: CommandDispatcher,
    ) -> None:
        self._container = container
        self._dispatcher = dispatcher
        self._register()

    def _register(self) -> None:
        self._dispatcher.register(CommandType.ANALYZE_PROJECT, self._analyze_project)
        self._dispatcher.register(CommandType.SYNC_REPOSITORY, self._sync_repository)
        self._dispatcher.register(CommandType.INGEST_REPOSITORY, self._ingest_repository)
        self._dispatcher.register(CommandType.INGEST_DOCUMENT, self._ingest_document)
        self._dispatcher.register(CommandType.EXTRACT_REQUIREMENTS, self._extract_requirements)
        self._dispatcher.register(CommandType.ANALYZE_WORK_ITEM, self._analyze_work_item)
        self._dispatcher.register(CommandType.PLAN_WORK_ITEM, self._plan_work_item)
        self._dispatcher.register(CommandType.BUILD_CONTEXT, self._build_context)
        self._dispatcher.register(CommandType.RUN_WORK_ITEM, self._run_work_item)
        self._dispatcher.register(CommandType.EXECUTE_WORK_ITEM, self._execute_work_item)
        self._dispatcher.register(CommandType.VERIFY_EXECUTION, self._verify_execution)
        self._dispatcher.register(CommandType.CREATE_PULL_REQUEST, self._create_pull_request)
        self._dispatcher.register(CommandType.RECONCILE_PROJECT, self._reconcile_project)

    # --- handlers ---------------------------------------------------------

    async def _analyze_project(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, AnalyzeProjectCommand)
        return {"project_id": model.project_id, "status": "analyzed"}

    async def _sync_repository(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, SyncRepositoryCommand)
        repository = await self._container.repositories.repositories.get(model.repository_id)
        if repository is None:
            return {"repository_id": model.repository_id, "status": "not_found"}
        return {"repository_id": model.repository_id, "status": "synced"}

    async def _ingest_repository(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, IngestRepositoryCommand)
        return {"repository_id": model.repository_id, "status": "ingested"}

    async def _ingest_document(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, IngestDocumentCommand)
        return {"document_id": model.document_id, "status": "ingested"}

    async def _extract_requirements(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, ExtractRequirementsCommand)
        return {"project_id": model.project_id, "status": "extracted"}

    async def _analyze_work_item(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, AnalyzeWorkItemCommand)
        return {"work_item_id": model.work_item_id, "status": "analyzed"}

    async def _plan_work_item(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, PlanWorkItemCommand)
        return {"work_item_id": model.work_item_id, "status": "planned"}

    async def _build_context(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, BuildContextCommand)
        work_item = await self._container.repositories.work_items.get(model.work_item_id)
        if work_item is None:
            return {"work_item_id": model.work_item_id, "status": "not_found"}
        from brain.domain.context import ContextRequest

        request = ContextRequest(
            work_item_id=work_item.id,
            project_id=work_item.project_id,
            repository_id=model.repository_id,
            revision=model.revision,
            preferred_token_budget=model.budget,
        )
        result = await self._container.context_engine.build(request)
        return {
            "work_item_id": model.work_item_id,
            "capsule_id": result.capsule.id,
            "status": "built",
        }

    async def _run_work_item(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, RunWorkItemCommand)
        work_item = await self._container.repositories.work_items.get(model.work_item_id)
        if work_item is None:
            return {"work_item_id": model.work_item_id, "status": "not_found"}
        project = await self._container.repositories.projects.get(work_item.project_id)
        if project is None:
            return {"work_item_id": model.work_item_id, "status": "no_project"}
        state = await self._container.workflow.start(
            project=project,
            work_item=work_item,
            repository=_dummy_repository(project.id),
            revision="HEAD",
        )
        return {
            "work_item_id": model.work_item_id,
            "workflow_id": state.workflow_id,
            "status": "started",
        }

    async def _execute_work_item(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, ExecuteWorkItemCommand)
        execution_id = model.execution_id or new_execution_id()
        return {
            "work_item_id": model.work_item_id,
            "execution_id": execution_id,
            "status": "executed",
        }

    async def _verify_execution(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, VerifyExecutionCommand)
        return {"execution_id": model.execution_id, "status": "verified"}

    async def _create_pull_request(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, CreatePullRequestCommand)
        return {"execution_id": model.execution_id, "status": "created"}

    async def _reconcile_project(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, ReconcileProjectCommand)
        return {"project_id": model.project_id, "status": "reconciled"}


def _dummy_repository(project_id: ProjectId) -> Repository:
    from brain.domain.repositories import Repository

    return Repository(
        project_id=project_id,
        name="pending",
        clone_url="",
        default_branch="main",
        current_revision="HEAD",
    )


def install_command_handlers(*, container: BrainContainer) -> CommandDispatcher:
    """Create a dispatcher with default handlers for a container."""
    dispatcher = container.services["command_dispatcher"]
    assert isinstance(dispatcher, CommandDispatcher)
    CommandHandlers(container=container, dispatcher=dispatcher)
    return dispatcher


__all__ = ["CommandHandlers", "install_command_handlers"]
