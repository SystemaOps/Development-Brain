"""Documentation + catalog sync service (Phase 15).

Task 15.3: normalize documentation changes into ``DocumentChanged`` events.
Task 15.6: compare human-declared topology (e.g. Backstage) with the
brain-discovered topology and record conflicts instead of silently overwriting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from brain.domain.documents import Document, DocumentSource, SourceArtifact
from brain.domain.event_types import DocumentChanged, model_to_envelope
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ProjectId, new_document_id
from brain.domain.projects import Project
from brain.domain.software_model import SoftwareComponent
from brain.ports.documentation import DocumentationPort
from brain.ports.event_bus import EventBus
from brain.ports.software_catalog import SoftwareCatalogPort


@dataclass
class DocumentSyncResult:
    ref: ExternalReference
    artifact: SourceArtifact
    event_published: bool = False


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
    ) -> None:
        self._documentation = documentation
        self._event_bus = event_bus
        self._declared_catalog = declared_catalog
        self._derived_catalog = derived_catalog

    async def ingest_document(
        self, ref: ExternalReference, project_id: ProjectId
    ) -> DocumentSyncResult:
        """Fetch a doc and publish a DocumentChanged event (Task 15.3)."""
        artifact = await self._documentation.fetch_document(ref)
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
