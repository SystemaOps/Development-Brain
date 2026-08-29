"""Project canonical events into canonical state.

:class:`CanonicalStateProjection` subscribes to canonical events and updates
canonical state through the repository ports.  It is idempotent: it always
uses upsert-style ``update`` calls, so re-applying an event (even one without
an idempotency key) yields the same state.

Handlers receive repository ports supplied by the caller so the projection is
adapter-agnostic.  When handlers must be atomic across several repositories
(PostgreSQL), run the projection inside a Unit of Work that owns the session.
"""

from __future__ import annotations

from brain.domain.event_types import (
    DocumentChanged,
    ExecutionCompleted,
    ExecutionRequested,
    ExecutionStarted,
    ProjectCreated,
    RepositoryRegistered,
    RequirementChanged,
    WorkItemChanged,
    WorkItemCreated,
    event_to_model,
)
from brain.domain.events import EventEnvelope
from brain.ports.event_bus import EventHandler
from brain.ports.repositories import (
    DocumentRepository,
    ExecutionRepository,
    ProjectRepository,
    RepositoryRepository,
    RequirementRepository,
    WorkItemRepository,
)


class CanonicalStateProjection(EventHandler):
    def __init__(
        self,
        *,
        projects: ProjectRepository,
        repositories: RepositoryRepository,
        work_items: WorkItemRepository,
        requirements: RequirementRepository,
        documents: DocumentRepository,
        executions: ExecutionRepository,
    ) -> None:
        self._projects = projects
        self._repositories = repositories
        self._work_items = work_items
        self._requirements = requirements
        self._documents = documents
        self._executions = executions

    async def handle(self, event: EventEnvelope) -> None:
        model = event_to_model(event)
        if isinstance(model, ProjectCreated):
            await self._projects.update(model.project)
        elif isinstance(model, RepositoryRegistered):
            await self._repositories.update(model.repository)
        elif isinstance(model, (WorkItemCreated, WorkItemChanged)):
            await self._work_items.update(model.work_item)
        elif isinstance(model, RequirementChanged):
            await self._requirements.update(model.requirement)
        elif isinstance(model, DocumentChanged):
            await self._documents.update(model.document)
        elif isinstance(model, (ExecutionRequested, ExecutionStarted, ExecutionCompleted)):
            await self._executions.update(model.execution)
