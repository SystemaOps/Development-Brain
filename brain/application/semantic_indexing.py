"""Semantic indexing service (Tasks 9.4, 9.5, 9.7).

Projects canonical sources into :class:`SemanticRecord` for the semantic
index: document nodes, requirements, decisions, and symbol-level code
summaries.  The index is an INDEX, never the source of truth -- this service
reads canonical state through ports and writes records through the
:class:`SemanticIndex` port.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from brain.domain.decisions import Decision
from brain.domain.identity import ProjectId, RepositoryId
from brain.domain.knowledge import SemanticRecord
from brain.domain.requirements import Requirement
from brain.ports.code_intelligence import CodeGraphRepository
from brain.ports.repositories import (
    DecisionRepository,
    DocumentRepository,
    RequirementRepository,
)
from brain.ports.semantic_index import SemanticIndex


@dataclass
class IndexingResult:
    project_id: ProjectId
    records: list[SemanticRecord] = field(default_factory=list)
    deleted: int = 0


class SemanticIndexingService:
    """Index canonical documents, requirements, decisions, and code summaries."""

    def __init__(
        self,
        *,
        index: SemanticIndex,
        documents: DocumentRepository,
        requirements: RequirementRepository,
        decisions: DecisionRepository,
        code_graph: CodeGraphRepository,
    ) -> None:
        self._index = index
        self._documents = documents
        self._requirements = requirements
        self._decisions = decisions
        self._code_graph = code_graph

    async def index_project(
        self,
        project_id: ProjectId,
        *,
        repository_id: RepositoryId | None = None,
        revision: str | None = None,
    ) -> IndexingResult:
        records: list[SemanticRecord] = []
        records.extend(await self._index_documents(project_id, repository_id, revision))
        records.extend(await self._index_requirements(project_id, revision))
        records.extend(await self._index_decisions(project_id, revision))
        if repository_id is not None and revision is not None:
            records.extend(await self._index_code_summaries(project_id, repository_id, revision))
        await self._index.index(records)
        return IndexingResult(project_id=project_id, records=records)

    async def _index_documents(
        self,
        project_id: ProjectId,
        repository_id: RepositoryId | None,
        revision: str | None,
    ) -> list[SemanticRecord]:
        records: list[SemanticRecord] = []
        for document in await self._documents.list_by_project(project_id):
            versions = await self._documents.list_versions(document.id)
            if not versions:
                continue
            current = max(versions, key=lambda v: v.ingested_at)
            nodes = await self._documents.list_nodes(current.id)
            for node in nodes:
                if not node.content:
                    continue
                records.append(
                    SemanticRecord(
                        entity_id=node.id,
                        entity_type="DocumentNode",
                        text=node.content,
                        project_id=project_id,
                        repository_id=repository_id or current.repository_id,
                        revision=revision or current.commit_sha,
                        source=node.heading_path[-1] if node.heading_path else document.title,
                        metadata={
                            "document_id": str(document.id),
                            "heading_path": list(node.heading_path),
                            "node_type": node.node_type.value,
                        },
                    )
                )
        return records

    async def _index_requirements(
        self, project_id: ProjectId, revision: str | None
    ) -> list[SemanticRecord]:
        records: list[SemanticRecord] = []
        for requirement in await self._requirements.list_by_project(project_id):
            text = _requirement_text(requirement)
            records.append(
                SemanticRecord(
                    entity_id=requirement.id,
                    entity_type="Requirement",
                    text=text,
                    project_id=project_id,
                    revision=revision,
                    source=requirement.key,
                    metadata={"title": requirement.title, "status": requirement.status.value},
                )
            )
        return records

    async def _index_decisions(
        self, project_id: ProjectId, revision: str | None
    ) -> list[SemanticRecord]:
        records: list[SemanticRecord] = []
        for decision in await self._decisions.list_by_project(project_id):
            records.append(
                SemanticRecord(
                    entity_id=decision.id,
                    entity_type="Decision",
                    text=_decision_text(decision),
                    project_id=project_id,
                    revision=revision,
                    source=decision.title,
                    metadata={"status": decision.status.value},
                )
            )
        return records

    async def _index_code_summaries(
        self,
        project_id: ProjectId,
        repository_id: RepositoryId,
        revision: str,
    ) -> list[SemanticRecord]:
        records: list[SemanticRecord] = []
        symbols = await self._code_graph.list_symbols(repository_id, revision)
        for symbol in symbols:
            if symbol.kind.value not in {"function", "method", "class"}:
                continue
            summary = _symbol_summary(symbol)
            if not summary:
                continue
            records.append(
                SemanticRecord(
                    entity_id=symbol.id,
                    entity_type="Symbol",
                    text=summary,
                    project_id=project_id,
                    repository_id=repository_id,
                    revision=revision,
                    source=symbol.qualified_name,
                    metadata={
                        "path": symbol.path,
                        "kind": symbol.kind.value,
                        "qualified_name": symbol.qualified_name,
                    },
                )
            )
        return records


def _requirement_text(requirement: Requirement) -> str:
    parts = [requirement.title, requirement.description]
    if requirement.key:
        parts.insert(0, requirement.key)
    return " ".join(part for part in parts if part)


def _decision_text(decision: Decision) -> str:
    parts = [decision.title, decision.context, decision.decision]
    if decision.alternatives:
        parts.append("Alternatives: " + "; ".join(decision.alternatives))
    if decision.consequences:
        parts.append("Consequences: " + "; ".join(decision.consequences))
    return " ".join(part for part in parts if part)


def _symbol_summary(symbol: object) -> str:
    """Deterministic summary for a code symbol (Task 9.5)."""
    parts: list[str] = []
    signature = str(getattr(symbol, "qualified_name", ""))
    parameters = getattr(symbol, "parameters", [])
    if parameters:
        signature += "(" + ", ".join(str(p) for p in parameters) + ")"
    return_annotation = getattr(symbol, "return_annotation", None)
    if return_annotation:
        signature += f" -> {return_annotation}"
    parts.append(signature)
    docstring = getattr(symbol, "docstring", None)
    if docstring:
        parts.append(str(docstring))
    decorators = getattr(symbol, "decorators", [])
    if decorators:
        parts.append("Decorators: " + ", ".join(str(d) for d in decorators))
    return " ".join(part for part in parts if part)


__all__ = ["IndexingResult", "SemanticIndexingService"]
