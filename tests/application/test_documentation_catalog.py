"""Unit tests for the Phase 15 documentation + catalog sync services."""

from __future__ import annotations

from datetime import datetime

from brain.adapters.catalog.backstage import BackstageCatalogAdapter
from brain.adapters.catalog.derived import DerivedCatalogPortAdapter
from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.repositories import (
    InMemorySoftwareCatalogRepository,
)
from brain.adapters.topology.catalog import DerivedSoftwareCatalog
from brain.application.documentation_catalog_sync import (
    DocumentationCatalogSyncService,
)
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import new_project_id
from brain.domain.projects import Project
from brain.domain.software_model import ComponentType, SoftwareComponent
from brain.ports.documentation import DocumentationPort


class _FakeDocumentation(DocumentationPort):
    async def fetch_document(self, ref: ExternalReference):
        from brain.domain.documents import SourceArtifact

        return SourceArtifact(
            source_uri=ref.external_id,
            provider=ref.provider,
            mime_type="text/markdown",
            file_name=ref.external_id,
            content=b"# doc\n",
        )

    async def list_changed_documents(self, since: datetime) -> list[ExternalReference]:
        return []

    async def search(self, query: str) -> list[ExternalReference]:
        return []


class _FakeBackstage:
    async def list_entities(self, kind: str) -> list[dict]:
        if kind == "Component":
            return [
                {
                    "metadata": {"name": "auth-api"},
                    "spec": {"type": "service", "lifecycle": "production"},
                }
            ]
        if kind == "Resource":
            return [{"metadata": {"name": "auth-db"}, "spec": {"type": "database"}}]
        return []


async def test_document_sync_publishes_changed_event() -> None:
    bus = InMemoryEventBus()
    service = DocumentationCatalogSyncService(documentation=_FakeDocumentation(), event_bus=bus)
    project_id = new_project_id()
    ref = ExternalReference(provider="git_markdown", external_id="README.md")
    result = await service.ingest_document(ref, project_id)
    assert result.event_published is True
    assert result.artifact.provider == "git_markdown"
    assert bus.published  # an event was published


async def test_backstage_adapter_reads_components() -> None:
    adapter = BackstageCatalogAdapter(transport=_FakeBackstage())
    project = Project(name="auth")
    components = await adapter.list_components(project)
    assert components
    assert components[0].name == "auth-api"
    assert components[0].component_type == ComponentType.BACKEND_SERVICE
    resources = await adapter.list_resources(project)
    assert resources
    assert resources[0].name == "auth-db"


async def test_derived_catalog_port_adapter() -> None:
    project = Project(name="auth")
    repo = InMemorySoftwareCatalogRepository()
    await repo.upsert_component(
        SoftwareComponent(
            project_id=project.id,
            name="auth",
            component_type=ComponentType.BACKEND_SERVICE,
        )
    )
    derived = DerivedSoftwareCatalog(repo)
    adapter = DerivedCatalogPortAdapter(derived)
    components = await adapter.list_components(project)
    assert [c.name for c in components] == ["auth"]


async def test_catalog_reconciliation_detects_conflict() -> None:
    project = Project(name="auth")
    declared_repo = InMemorySoftwareCatalogRepository()
    discovered_repo = InMemorySoftwareCatalogRepository()

    # Declared: auth is a library. Discovered: auth is a backend service.
    await declared_repo.upsert_component(
        SoftwareComponent(project_id=project.id, name="auth", component_type=ComponentType.LIBRARY)
    )
    await discovered_repo.upsert_component(
        SoftwareComponent(
            project_id=project.id,
            name="auth",
            component_type=ComponentType.BACKEND_SERVICE,
        )
    )

    service = DocumentationCatalogSyncService(
        documentation=_FakeDocumentation(),
        event_bus=InMemoryEventBus(),
        declared_catalog=DerivedCatalogPortAdapter(DerivedSoftwareCatalog(declared_repo)),
        derived_catalog=DerivedCatalogPortAdapter(DerivedSoftwareCatalog(discovered_repo)),
    )
    result = await service.reconcile_catalog(project)
    assert result.conflicts
    conflict = result.conflicts[0]
    assert conflict.component_name == "auth"
    assert conflict.declared_type == "library"
    assert conflict.discovered_type == "backend_service"


async def test_catalog_reconciliation_merges_without_overwrite() -> None:
    project = Project(name="auth")
    declared_repo = InMemorySoftwareCatalogRepository()
    discovered_repo = InMemorySoftwareCatalogRepository()
    await declared_repo.upsert_component(
        SoftwareComponent(project_id=project.id, name="auth", component_type=ComponentType.LIBRARY)
    )
    await discovered_repo.upsert_component(
        SoftwareComponent(
            project_id=project.id,
            name="auth",
            component_type=ComponentType.BACKEND_SERVICE,
        )
    )
    service = DocumentationCatalogSyncService(
        documentation=_FakeDocumentation(),
        event_bus=InMemoryEventBus(),
        declared_catalog=DerivedCatalogPortAdapter(DerivedSoftwareCatalog(declared_repo)),
        derived_catalog=DerivedCatalogPortAdapter(DerivedSoftwareCatalog(discovered_repo)),
    )
    result = await service.reconcile_catalog(project)
    # Neither side is overwritten: the conflict is recorded and the merged view
    # contains the component (the discovered type wins for the merged view).
    assert len(result.merged_components) >= 1
    assert any(c.name == "auth" for c in result.merged_components)
