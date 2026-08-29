"""Phase 15 golden tests and completion gate.

The brain operates WITHOUT XWiki/Confluence/Backstage (using git-markdown docs
and the derived catalog from discovered topology), but can ingest them when
configured.  No external provider is mandatory.
"""

from __future__ import annotations

from brain.adapters.catalog.backstage import BackstageCatalogAdapter
from brain.adapters.catalog.derived import DerivedCatalogPortAdapter
from brain.adapters.documentation.git_markdown import (
    GitMarkdownDocumentationAdapter,
)
from brain.adapters.documentation.xwiki import XWikiDocumentationAdapter
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
from brain.domain.repositories import Repository
from brain.domain.software_model import ComponentType, SoftwareComponent


class _FakeGitTransport:
    async def read_file(self, repository: Repository, path: str, revision: str) -> bytes:
        return b"# docs\n"

    async def tree(self, repository: Repository, revision: str) -> list[str]:
        return ["README.md", "docs/architecture.md"]


class _FakeXWiki:
    async def get_page(self, page_id: str) -> dict:
        return {"id": page_id, "title": "Page", "version": "1", "content": "<p>x</p>"}

    async def get_page_version(self, page_id: str, version: str) -> dict:
        return {"id": page_id, "title": "Page", "version": version, "content": "x"}

    async def list_page_changes(self, page_id: str) -> list[dict]:
        return []

    async def get_attachments(self, page_id: str) -> list[dict]:
        return []

    async def get_children(self, page_id: str) -> list[dict]:
        return []

    async def get_links(self, page_id: str) -> list[str]:
        return []

    async def list_changed_pages(self, since) -> list[str]:
        return ["Space.Home"]


class _FakeBackstage:
    async def list_entities(self, kind: str) -> list[dict]:
        if kind == "Component":
            return [{"metadata": {"name": "auth-api"}, "spec": {"type": "service"}}]
        if kind == "Resource":
            return [{"metadata": {"name": "auth-db"}, "spec": {"type": "database"}}]
        return []


def _git_doc_adapter() -> GitMarkdownDocumentationAdapter:
    repository = Repository(
        project_id=new_project_id(), name="auth", clone_url="git@example:auth.git"
    )
    return GitMarkdownDocumentationAdapter(
        repository=repository, transport=_FakeGitTransport(), revision="abc"
    )


async def test_gate_brain_works_without_external_wiki() -> None:
    """The derived catalog works with no external catalog configured."""
    project = Project(name="auth")
    repo = InMemorySoftwareCatalogRepository()
    await repo.upsert_component(
        SoftwareComponent(
            project_id=project.id,
            name="auth",
            component_type=ComponentType.BACKEND_SERVICE,
        )
    )
    adapter = DerivedCatalogPortAdapter(DerivedSoftwareCatalog(repo))
    components = await adapter.list_components(project)
    assert [c.name for c in components] == ["auth"]


async def test_gate_git_markdown_is_default_docs_provider() -> None:
    """Repository docs are ingested without any external wiki."""
    adapter = _git_doc_adapter()
    ref = ExternalReference(provider="git_markdown", external_id="README.md")
    artifact = await adapter.fetch_document(ref)
    assert artifact.provider == "git_markdown"
    assert artifact.content == b"# docs\n"


async def test_gate_xwiki_ingests_when_configured() -> None:
    """XWiki is optional but works when configured."""
    adapter = XWikiDocumentationAdapter(transport=_FakeXWiki(), wiki="test")
    ref = ExternalReference(provider="xwiki", external_id="Space.Home")
    artifact = await adapter.fetch_document(ref)
    assert artifact.provider == "xwiki"
    assert artifact.revision == "1"


async def test_gate_backstage_is_optional_enrichment() -> None:
    """Backstage is optional; when configured it enriches the catalog."""
    project = Project(name="auth")
    adapter = BackstageCatalogAdapter(transport=_FakeBackstage())
    components = await adapter.list_components(project)
    assert components
    assert components[0].name == "auth-api"
    resources = await adapter.list_resources(project)
    assert resources


async def test_gate_doc_sync_publishes_changed_events() -> None:
    service = DocumentationCatalogSyncService(
        documentation=_git_doc_adapter(), event_bus=InMemoryEventBus()
    )
    project_id = new_project_id()
    result = await service.ingest_document(
        ExternalReference(provider="git_markdown", external_id="docs/architecture.md"),
        project_id,
    )
    assert result.event_published is True


async def test_gate_catalog_reconciliation_without_overwrite() -> None:
    """Declared (Backstage) vs discovered (brain) disagreement is recorded,
    never silently overwritten."""
    project = Project(name="auth")
    declared = InMemorySoftwareCatalogRepository()
    discovered = InMemorySoftwareCatalogRepository()
    await declared.upsert_component(
        SoftwareComponent(project_id=project.id, name="auth", component_type=ComponentType.LIBRARY)
    )
    await discovered.upsert_component(
        SoftwareComponent(
            project_id=project.id,
            name="auth",
            component_type=ComponentType.BACKEND_SERVICE,
        )
    )
    service = DocumentationCatalogSyncService(
        documentation=_git_doc_adapter(),
        event_bus=InMemoryEventBus(),
        declared_catalog=DerivedCatalogPortAdapter(DerivedSoftwareCatalog(declared)),
        derived_catalog=DerivedCatalogPortAdapter(DerivedSoftwareCatalog(discovered)),
    )
    result = await service.reconcile_catalog(project)
    assert result.conflicts
    assert any(c.component_name == "auth" for c in result.conflicts)
