"""Incremental repository revision handling (Phase 4.5).

:class:`IncrementalRevisionHandler` reacts to ``RepositoryRevisionChanged``
canonical events:

1. loads the repository aggregate;
2. asks the :class:`~brain.ports.source_control.SourceControlPort` for the
   changed files between the old and new revisions;
3. classifies each file into a :class:`~brain.domain.repository_scan.FileCategory`;
4. persists a :class:`~brain.domain.repository_scan.RepositoryChangeSet` (the
   durable "ingestion job") so later phases (document ingestion, topology
   discovery, code intelligence) can consume exactly what changed;
5. advances the repository's ``current_revision``.

The handler only knows ports, so it runs unchanged against the in-memory
reference adapters and PostgreSQL.  Wrap its event handling in a Unit of Work
when the change set and the repository update must be atomic.
"""

from __future__ import annotations

from brain.domain.event_types import (
    RepositoryRevisionChanged,
    event_to_model,
)
from brain.domain.events import EventEnvelope
from brain.domain.repository_scan import (
    RepositoryChangeSet,
    classify_changed_files,
)
from brain.ports.event_bus import EventHandler
from brain.ports.repositories import RepositoryRepository
from brain.ports.repository_scan import RepositoryChangeSetRepository
from brain.ports.source_control import SourceControlPort


class IncrementalRevisionHandler(EventHandler):
    def __init__(
        self,
        *,
        repositories: RepositoryRepository,
        source_control: SourceControlPort,
        change_sets: RepositoryChangeSetRepository,
    ) -> None:
        self._repositories = repositories
        self._source_control = source_control
        self._change_sets = change_sets

    async def handle(self, event: EventEnvelope) -> None:
        model = event_to_model(event)
        if not isinstance(model, RepositoryRevisionChanged):
            return
        repository = await self._repositories.get(model.repository_id)
        if repository is None:
            return

        changed = await self._source_control.list_changed_files(
            repository, model.old_revision or "", model.new_revision
        )
        change_set = RepositoryChangeSet(
            repository_id=model.repository_id,
            old_revision=model.old_revision,
            new_revision=model.new_revision,
            files=classify_changed_files(changed),
        )
        await self._change_sets.save_change_set(change_set)
        await self._repositories.update(
            repository.model_copy(update={"current_revision": model.new_revision})
        )


__all__ = ["IncrementalRevisionHandler"]
