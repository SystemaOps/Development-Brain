"""Document ingestion service (Phase 5).

Orchestrates the canonical ingestion pipeline:

1. select a parser through the registry;
2. parse a :class:`~brain.domain.documents.SourceArtifact` into a
   :class:`~brain.domain.parsing.ParsedDocument`;
3. extract references (Task 5.8) and keep the unresolved ones separately;
4. version the document (Task 5.9): compare content hash, preserve old
   versions, advance the current-version pointer;
5. persist the parsed nodes as canonical ``DocumentNode`` rows;
6. create ``Decision`` entities for ADRs (Task 5.6);
7. generate semantic chunks only after the structure exists (Task 5.10);
8. publish a ``DocumentChanged`` canonical event.

The service depends only on ports, so it runs unchanged against the in-memory
reference adapters and PostgreSQL.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from brain.domain.decisions import Decision, DecisionStatus
from brain.domain.documents import (
    Document,
    DocumentNode,
    DocumentSource,
    DocumentType,
    DocumentVersion,
    SourceArtifact,
)
from brain.domain.event_types import DocumentChanged, model_to_envelope
from brain.domain.identity import DocumentVersionId, ProjectId, RepositoryId
from brain.domain.parsing import (
    ExtractedReference,
    ParsedDocument,
    ReferenceKind,
    SemanticChunk,
)
from brain.ports.event_bus import EventBus
from brain.ports.parsing import (
    EntityExtractor,
    ParserRegistry,
    ReferenceExtractor,
)
from brain.ports.repositories import DecisionRepository, DocumentRepository


@dataclass
class DocumentIngestionResult:
    document: Document
    version: DocumentVersion
    created_new_version: bool
    nodes: list[DocumentNode] = field(default_factory=list)
    chunks: list[SemanticChunk] = field(default_factory=list)
    unresolved_references: list[ExtractedReference] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)


class DocumentIngestionService:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        parser_registry: ParserRegistry,
        entity_extractor: EntityExtractor,
        reference_extractor: ReferenceExtractor,
        decisions: DecisionRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._documents = documents
        self._parsers = parser_registry
        self._extractor = entity_extractor
        self._reference_extractor = reference_extractor
        self._decisions = decisions
        self._event_bus = event_bus

    async def ingest(
        self,
        artifact: SourceArtifact,
        *,
        project_id: ProjectId,
        document_type: DocumentType | None = None,
        repository_id: RepositoryId | None = None,
        commit_sha: str | None = None,
    ) -> DocumentIngestionResult:
        if artifact.content_hash is None:
            artifact = artifact.model_copy(update={"content_hash": _content_hash(artifact)})

        parser = self._parsers.select(artifact)
        if parser is None:
            raise ValueError(f"no parser registered for artifact {artifact.source_uri!r}")
        parsed = parser.parse(artifact)
        parsed = self._enrich_references(parsed)
        parsed = self._collect_candidates(parsed)

        doc_type = document_type or parsed.document_type
        source = DocumentSource(
            provider=artifact.provider,
            uri=artifact.source_uri,
            mime_type=artifact.mime_type,
        )

        existing = await self._documents.find_by_source(project_id, artifact.source_uri)
        if existing is not None:
            document = existing
            current_version = (
                await self._documents.get_version(existing.current_version_id)
                if existing.current_version_id
                else None
            )
        else:
            document = Document(
                project_id=project_id,
                type=doc_type,
                title=parsed.title or _default_title(artifact),
                source=source,
            )
            await self._documents.create(document)
            current_version = None

        created_new = current_version is None or current_version.checksum != artifact.content_hash

        if not created_new:
            assert current_version is not None
            nodes = await self._documents.list_nodes(current_version.id)
            return DocumentIngestionResult(
                document=document,
                version=current_version,
                created_new_version=False,
                nodes=nodes,
                chunks=_chunks(document, current_version, nodes),
                unresolved_references=parsed.unresolved_references,
            )

        version = DocumentVersion(
            document_id=document.id,
            source_version=artifact.revision,
            repository_id=repository_id,
            commit_sha=commit_sha,
            checksum=artifact.content_hash or "",
            content_uri=artifact.raw_bytes_ref,
        )
        await self._documents.add_version(version)

        nodes = await self._persist_nodes(parsed, version.id)
        document = document.model_copy(update={"current_version_id": version.id, "type": doc_type})
        await self._documents.update(document)

        decisions = await self._create_decisions(parsed, project_id)
        chunks = _chunks(document, version, nodes)

        if self._event_bus is not None:
            envelope = model_to_envelope(
                DocumentChanged(document=document),
                source=artifact.provider,
                project_id=document.project_id,
            )
            await self._event_bus.publish(envelope)

        return DocumentIngestionResult(
            document=document,
            version=version,
            created_new_version=True,
            nodes=nodes,
            chunks=chunks,
            unresolved_references=parsed.unresolved_references,
            decisions=decisions,
        )

    async def _persist_nodes(
        self, parsed: ParsedDocument, version_id: DocumentVersionId
    ) -> list[DocumentNode]:
        nodes: list[DocumentNode] = []
        for node in parsed.nodes:
            unresolved = [r.value for r in node.references if not r.resolved]
            doc_node = DocumentNode(
                id=node.id,
                version_id=version_id,
                node_type=node.node_type,
                title=node.title,
                heading_path=list(node.heading_path),
                content=node.content,
                parent_id=node.parent_id,
                child_ids=list(node.child_ids),
                links=list(node.links),
                unresolved_refs=unresolved,
            )
            await self._documents.add_node(doc_node)
            nodes.append(doc_node)
        return nodes

    def _enrich_references(self, parsed: ParsedDocument) -> ParsedDocument:
        unresolved: list[ExtractedReference] = []
        for node in parsed.nodes:
            refs = self._reference_extractor.extract(node)
            node.references = refs
            unresolved.extend(ref for ref in refs if not ref.resolved)
        seen: set[tuple[str, str]] = set()
        deduped = []
        for ref in unresolved:
            key = (ref.kind.value, ref.value)
            if key not in seen:
                seen.add(key)
                deduped.append(ref)
        parsed.unresolved_references = deduped
        return parsed

    def _collect_candidates(self, parsed: ParsedDocument) -> ParsedDocument:
        for candidate in self._extractor.extract(parsed):
            parsed.unresolved_references.append(
                ExtractedReference(
                    kind=ReferenceKind.REQUIREMENT,
                    value=candidate.title,
                    raw=candidate.source_uri,
                )
            )
        return parsed

    async def _create_decisions(
        self, parsed: ParsedDocument, project_id: ProjectId
    ) -> list[Decision]:
        if self._decisions is None or parsed.adr_sections is None:
            return []
        sections = parsed.adr_sections
        status = _adr_status(parsed.front_matter.get("adr_status"))
        decision = Decision(
            project_id=project_id,
            title=parsed.title or parsed.source.source_uri,
            context=sections.context,
            decision=sections.decision,
            alternatives=sections.alternatives,
            consequences=sections.consequences,
            status=status,
        )
        await self._decisions.create(decision)
        return [decision]


def _adr_status(value: object) -> DecisionStatus:
    if isinstance(value, str):
        lowered = value.strip().lower()
        for status in DecisionStatus:
            if status.value == lowered:
                return status
    return DecisionStatus.PROPOSED


def _content_hash(artifact: SourceArtifact) -> str:
    data = artifact.content or artifact.raw_bytes_ref or artifact.source_uri
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _default_title(artifact: SourceArtifact) -> str:
    name = artifact.file_name or artifact.source_uri.rsplit("/", 1)[-1] or artifact.source_uri
    return name


def _chunks(
    document: Document, version: DocumentVersion, nodes: list[DocumentNode]
) -> list[SemanticChunk]:
    chunks: list[SemanticChunk] = []
    for index, node in enumerate(nodes):
        if not node.content:
            continue
        chunks.append(
            SemanticChunk(
                document_id=document.id,
                version_id=version.id,
                node_id=node.id,
                heading_path=list(node.heading_path),
                content=node.content,
                project_id=document.project_id,
                repository_id=version.repository_id,
                commit_sha=version.commit_sha,
                document_type=document.type,
                chunk_index=index,
            )
        )
    return chunks


__all__ = ["DocumentIngestionResult", "DocumentIngestionService"]
