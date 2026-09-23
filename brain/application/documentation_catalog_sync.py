"""Documentation + catalog sync service (Phase 15).

Task 15.3: normalize documentation changes into ``DocumentChanged`` events.
Task 15.6: compare human-declared topology (e.g. Backstage) with the
brain-discovered topology and record conflicts instead of silently overwriting.

Since the XWiki ingestion runtime (Step 7), ``ingest_document`` delegates to
the canonical :class:`DocumentIngestionService` — parsing, versioning, nodes
and semantic chunks all happen there.  This service keeps only
discovery/catalog responsibilities; it must never become a second partial
ingestion path (fix-plan §7/§8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from brain.application.document_ingestion import (
    DocumentIngestionResult,
    DocumentIngestionService,
)
from brain.domain.documents import Document, DocumentSource, SourceArtifact
from brain.domain.event_types import DocumentChanged, model_to_envelope
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import (
    DocumentId,
    DocumentVersionId,
    ProjectId,
    new_document_id,
)
from brain.domain.projects import Project
from brain.domain.software_model import SoftwareComponent
from brain.ports.documentation import DocumentationPort
from brain.ports.event_bus import EventBus
from brain.ports.software_catalog import SoftwareCatalogPort


class _DocumentIngestion(Protocol):
    async def ingest(
        self,
        artifact: SourceArtifact,
        *,
        project_id: ProjectId,
        document_type: object | None = None,
        repository_id: object | None = None,
        commit_sha: str | None = None,
    ) -> DocumentIngestionResult: ...


@dataclass
class DocumentSyncResult:
    ref: ExternalReference
    artifact: SourceArtifact
    event_published: bool = False
    document_id: DocumentId | None = None
    version_id: DocumentVersionId | None = None


@dataclass
class CatalogConflict:
    component_name: str
    declared_type: str
    discovered_type: str


@dataclass
class CatalogReconciliationResult:
    project_id: ProjectId
    conflicts: list[CatalogConflict] = field(default_factory=list)
    merged_components: list[SoftwareComponent] = field(default_factory=list)


class DocumentationCatalogSyncService:
    """Syncs external documentation and catalogs into the brain."""

    def __init__(
        self,
        *,
        documentation: DocumentationPort,
        event_bus: EventBus,
        declared_catalog: SoftwareCatalogPort | None = None,
        derived_catalog: SoftwareCatalogPort | None = None,
        ingestion: DocumentIngestionService | None = None,
    ) -> None:
        self._documentation = documentation
        self._event_bus = event_bus
        self._declared_catalog = declared_catalog
        self._derived_catalog = derived_catalog
        self._ingestion = ingestion

    async def ingest_document(
        self, ref: ExternalReference, project_id: ProjectId
    ) -> DocumentSyncResult:
        """Fetch a doc and ingest it through the canonical pipeline (Step 7).

        When no ``DocumentIngestionService`` is wired (tests/legacy), a
        ``DocumentChanged`` event is still published for the fetched artifact;
        otherwise the ingestion service owns parsing, versioning, nodes and
        the ``DocumentChanged`` event.
        """
        artifact = await self._documentation.fetch_document(ref)
        if self._ingestion is not None:
            ingested = await self._ingestion.ingest(artifact, project_id=project_id)
            return DocumentSyncResult(
                ref=ref,
                artifact=artifact,
                event_published=True,
                document_id=ingested.document.id,
                version_id=ingested.version.id,
            )
        document = Document(
            id=new_document_id(),
            project_id=project_id,
            title=artifact.file_name or artifact.source_uri,
            source=DocumentSource(provider=artifact.provider, uri=artifact.source_uri),
        )
        # Publish a DocumentChanged event referencing the canonical document.
        await self._event_bus.publish(
            model_to_envelope(
                DocumentChanged(document=document),
                source=ref.provider,
            )
        )
        return DocumentSyncResult(ref=ref, artifact=artifact, event_published=True)

    async def reconcile_catalog(self, project: Project) -> CatalogReconciliationResult:
        """Compare declared vs discovered topology; keep both on conflict (15.6)."""
        result = CatalogReconciliationResult(project_id=project.id)
        if self._declared_catalog is None or self._derived_catalog is None:
            return result

        declared_components = await self._declared_catalog.list_components(project)
        derived_components = await self._derived_catalog.list_components(project)

        discovered_by_name = {c.name: c for c in derived_components}
        for declared in declared_components:
            discovered = discovered_by_name.get(declared.name)
            if discovered is None:
                # Declared-only: keep it in the merged view.
                result.merged_components.append(declared)
                continue
            if discovered.component_type != declared.component_type:
                result.conflicts.append(
                    CatalogConflict(
                        component_name=declared.name,
                        declared_type=declared.component_type.value,
                        discovered_type=discovered.component_type.value,
                    )
                )
            result.merged_components.append(discovered)

        result.merged_components.extend(c for c in derived_components)
        # De-duplicate merged list by name, preferring declared.
        seen: set[str] = set()
        merged: list[SoftwareComponent] = []
        for component in result.merged_components:
            if component.name in seen:
                continue
            seen.add(component.name)
            merged.append(component)
        result.merged_components = merged
        return result


__all__ = [
    "CatalogConflict",
    "CatalogReconciliationResult",
    "DocumentSyncResult",
    "DocumentationCatalogSyncService",
]
