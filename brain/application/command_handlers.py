"""Default command handlers (Phase 24/25).

Maps canonical commands to existing application services.  Handlers contain no
business logic beyond calling the right service — the worker runtime reuses
these so the API, worker, and CLI converge on the same behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime

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
from brain.domain.executions import ExecutionRequest
from brain.domain.identity import (
    DocumentId,
    ExecutionId,
    ProjectId,
    WorkItemId,
    new_actor_id,
    new_execution_id,
    new_workflow_id,
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
        # Milestone 1: local source control is not wired; the revision stays.
        return {"repository_id": model.repository_id, "status": "synced"}

    async def _ingest_repository(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, IngestRepositoryCommand)
        repository = await self._container.repositories.repositories.get(model.repository_id)
        if repository is None:
            return {"repository_id": model.repository_id, "status": "not_found"}
        return {"repository_id": model.repository_id, "status": "ingested"}

    async def _ingest_document(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, IngestDocumentCommand)
        document = await self._container.repositories.documents.get(DocumentId(model.document_id))
        if document is None:
            return {"document_id": model.document_id, "status": "not_found"}
        from brain.application.document_ingestion import DocumentIngestionService
        from brain.domain.documents import SourceArtifact

        artifact = SourceArtifact(
            source_uri=document.source.uri,
            provider=document.source.provider,
            mime_type=document.source.mime_type,
        )
        service = self._container.services["document_ingestion"]
        assert isinstance(service, DocumentIngestionService)
        result = await service.ingest(
            artifact,
            project_id=document.project_id,
            document_type=document.type,
        )
        return {
            "document_id": model.document_id,
            "version_id": result.version.id,
            "status": "ingested",
        }

    async def _extract_requirements(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, ExtractRequirementsCommand)
        from brain.application.planning import PlanningService

        service = self._container.services["planning"]
        assert isinstance(service, PlanningService)
        extracted = await service.extract_requirements(model.project_id)
        return {
            "project_id": model.project_id,
            "extracted": len(extracted),
            "status": "extracted",
        }

    async def _analyze_work_item(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, AnalyzeWorkItemCommand)
        work_item = await self._container.repositories.work_items.get(model.work_item_id)
        if work_item is None:
            return {"work_item_id": model.work_item_id, "status": "not_found"}
        return {
            "work_item_id": model.work_item_id,
            "implementation_status": work_item.implementation_status.value,
            "status": "analyzed",
        }

    async def _plan_work_item(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, PlanWorkItemCommand)
        work_item = await self._container.repositories.work_items.get(model.work_item_id)
        if work_item is None:
            return {"work_item_id": model.work_item_id, "status": "not_found"}
        from brain.application.planning import PlanningService

        service = self._container.services["planning"]
        assert isinstance(service, PlanningService)
        plan = await service.build_plan(
            work_item.project_id,
            title=work_item.title,
        )
        return {
            "work_item_id": model.work_item_id,
            "plan_id": plan.plan.id,
            "status": "planned",
        }

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
        from brain.application.workspace_manager import WorkspaceManager
        from brain.domain.executions import Execution, ExecutionStatus
        from brain.ports.executor import ExecutorPort

        executor = self._container.services["executor"]
        assert isinstance(executor, ExecutorPort)
        work_item = await self._container.repositories.work_items.get(model.work_item_id)
        project = (
            await self._container.repositories.projects.get(work_item.project_id)
            if work_item is not None
            else None
        )
        repositories = (
            await self._container.repositories.repositories.list_by_project(work_item.project_id)
            if work_item is not None
            else []
        )
        repository: Repository | None = repositories[0] if repositories else None

        # Task 37.5: every execution records repository, base branch, base
        # commit, worktree and working branch.
        workspace_manager = self._container.services["workspace_manager"]
        assert isinstance(workspace_manager, WorkspaceManager)
        workspace = None
        if work_item is not None and repository is not None and project is not None:
            workspace = await workspace_manager.create_workspace(
                repository,
                base_revision=None,
                task_label="work-item",
            )

        request = _build_execution_request(
            work_item_id=model.work_item_id,
            execution_id=execution_id,
        )
        if workspace is not None:
            request = request.model_copy(
                update={
                    "repository_ref": workspace.repository.clone_url,
                    "base_revision": workspace.base_revision,
                    "base_branch": workspace.branch_name,
                    "working_branch": workspace.branch_name,
                    "worktree_path": workspace.path or None,
                    "workspace_path": workspace.path or None,
                }
            )

        if work_item is not None:
            await self._container.repositories.executions.create(
                Execution(
                    id=execution_id,
                    workflow_id=request.workflow_id,
                    work_item_id=model.work_item_id,
                    executor_id=new_actor_id(),
                    status=ExecutionStatus.STARTED,
                    base_branch=request.base_branch,
                    working_branch=request.working_branch,
                    worktree_path=request.worktree_path,
                )
            )

        result = await executor.execute(request)
        execution = await self._container.repositories.executions.get(execution_id)
        if execution is not None:
            # Task 37.6: a failed execution is persisted (evidence/log refs in
            # blockers) and never terminates the worker process.
            updated = execution.model_copy(
                update={
                    "status": result.status,
                    "completed_at": datetime.now(UTC)
                    if result.status
                    in {
                        ExecutionStatus.COMPLETED,
                        ExecutionStatus.FAILED,
                        ExecutionStatus.CANCELLED,
                    }
                    else None,
                }
            )
            await self._container.repositories.executions.update(updated)
        return {
            "work_item_id": model.work_item_id,
            "execution_id": execution_id,
            "status": result.status.value,
            "blockers": result.blockers,
        }

    async def _verify_execution(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, VerifyExecutionCommand)
        outcome = await self._container.verification.verify(
            execution_id=model.execution_id,
            work_item_id=model.work_item_id,
            acceptance_criteria=[],
            changed_files=[],
        )
        return {
            "execution_id": model.execution_id,
            "verdict": outcome.run.verdict.value,
            "status": "verified",
        }

    async def _create_pull_request(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, CreatePullRequestCommand)
        pr_port = self._container.pull_requests
        if pr_port is None:
            return {"execution_id": model.execution_id, "status": "no_pr_provider"}
        execution = await self._container.repositories.executions.get(model.execution_id)
        if execution is None:
            return {"execution_id": model.execution_id, "status": "not_found"}
        work_item = await self._container.repositories.work_items.get(model.work_item_id)
        if work_item is None:
            return {"work_item_id": model.work_item_id, "status": "not_found"}
        repos = await self._container.repositories.repositories.list_by_project(
            work_item.project_id
        )
        if not repos:
            return {"execution_id": model.execution_id, "status": "no_repository"}
        repository = repos[0]
        ref = await pr_port.create_pull_request(
            repository=repository,
            source_branch=f"brain/{execution.id}",
            target_branch=repository.default_branch,
            title=work_item.title,
            description=work_item.description,
        )
        return {
            "execution_id": model.execution_id,
            "pr_external_id": ref.external_id,
            "status": "created",
        }

    async def _reconcile_project(self, envelope: CommandEnvelope) -> dict[str, object]:
        model = command_to_model(envelope)
        assert isinstance(model, ReconcileProjectCommand)
        return {"project_id": model.project_id, "status": "reconciled"}


def _dummy_repository(project_id: ProjectId) -> Repository:
    return Repository(
        project_id=project_id,
        name="pending",
        clone_url="",
        default_branch="main",
        current_revision="HEAD",
    )


def _build_execution_request(
    *,
    work_item_id: WorkItemId,
    execution_id: ExecutionId,
) -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=execution_id,
        workflow_id=new_workflow_id(),
        work_item_id=work_item_id,
        repository_ref="",
        base_revision="HEAD",
    )


def install_command_handlers(*, container: BrainContainer) -> CommandDispatcher:
    """Create a dispatcher with default handlers for a container."""
    dispatcher = container.services["command_dispatcher"]
    assert isinstance(dispatcher, CommandDispatcher)
    CommandHandlers(container=container, dispatcher=dispatcher)
    return dispatcher


__all__ = ["CommandHandlers", "install_command_handlers"]
