"""In-memory semantic index reference implementation.

Lexical containment scoring over lowercased tokens; useful for contract tests
and early development, never a production-grade search.
"""

from __future__ import annotations

import re
import threading
import uuid

from brain.domain.knowledge import SemanticRecord

_WORD_SPLIT = re.compile(r"\W+")


class InMemorySemanticIndex:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[uuid.UUID, SemanticRecord] = {}

    async def index(self, records: list[SemanticRecord]) -> None:
        with self._lock:
            for record in records:
                self._records[record.record_id] = record

    async def delete(self, ids: list[uuid.UUID]) -> None:
        with self._lock:
            for record_id in ids:
                self._records.pop(record_id, None)

    async def search(
        self, query: str, filters: dict[str, object], limit: int
    ) -> list[SemanticRecord]:
        tokens = [t for t in _WORD_SPLIT.split(query.lower()) if t]
        with self._lock:
            scored: list[tuple[int, SemanticRecord]] = []
            for record in self._records.values():
                if not _matches_filters(record, filters):
                    continue
                text = record.text.lower()
                score = sum(1 for token in tokens if token in text)
                if score > 0:
                    scored.append((score, record))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [record for _, record in scored[:limit]]


def _matches_filters(record: SemanticRecord, filters: dict[str, object]) -> bool:
    project = filters.get("project_id")
    repository = filters.get("repository_id")
    revision = filters.get("revision")
    entity_type = filters.get("entity_type")
    return (
        (project is None or record.project_id == project)
        and (repository is None or record.repository_id == repository)
        and (revision is None or record.revision == revision)
        and (entity_type is None or record.entity_type == entity_type)
    )
