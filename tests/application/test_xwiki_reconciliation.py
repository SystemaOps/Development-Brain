"""Step 6 tests: XWiki documentation reconciliation service.

Per the fix plan §16:

- initial sync (no watermark) ingests all pages and stores the watermark;
- incremental sync ingests only pages modified after the watermark;
- one malformed/unmapped page never aborts the cycle and the watermark is
  not advanced past failures;
- the scheduler performs real ingestion (gate test in test_phase45).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from brain.adapters.in_memory.repositories import (
    InMemoryDocumentRepository,
    InMemoryProjectRepository,
    InMemorySyncWatermarkRepository,
)
from brain.adapters.parsers.registry import DefaultParserRegistry
from brain.adapters.parsers.xwiki_syntax import XWikiSyntaxParser
from brain.application.document_ingestion import DocumentIngestionService
from brain.application.xwiki_ingestion import (
    XWikiDocumentationSyncService,
    XWikiProjectResolver,
    XWikiWatermarks,
)
from brain.domain.documents import SourceArtifact
from brain.domain.external_reference import ExternalReference
from brain.domain.projects import Project


def _ref(page_id: str) -> ExternalReference:
    return ExternalReference(
        provider="xwiki", external_id=page_id, external_type="page", namespace="xwiki"
    )


def _artifact(page_id: str, content: str = "== Page ==\n\nbody") -> SourceArtifact:
    return SourceArtifact(
        source_uri=page_id,
        provider="xwiki",
        mime_type="text/x-xwiki",
        file_name=page_id,
        revision="1.1",
        content=content.encode("utf-8"),
        metadata={"syntax": "xwiki/2.1", "space": page_id.split(".")[0]},
    )


class _FakeXWikiPort:
    """Fake DocumentationPort with since filtering (adapter responsibility)."""

    def __init__(
        self,
        pages: dict[str, tuple[datetime, SourceArtifact]],
        *,
        failing: set[str] | None = None,
    ) -> None:
        self._pages = pages
        self._failing = failing or set()
        self.fetched: list[str] = []

    async def fetch_document(self, ref: ExternalReference) -> SourceArtifact:
        self.fetched.append(ref.external_id)
        if ref.external_id in self._failing:
            raise RuntimeError(f"fetch boom: {ref.external_id}")
        return self._pages[ref.external_id][1]

    async def list_changed_documents(
        self,
        since: datetime | None = None,
        *,
        spaces: list[str] | None = None,
    ) -> list[ExternalReference]:
        refs = []
        for page_id, (modified, _) in self._pages.items():
            if since is not None and modified <= since:
                continue
            if spaces and page_id.split(".")[0] not in spaces:
                continue
            refs.append(_ref(page_id))
        return refs

    async def search(self, query: str) -> list[ExternalReference]:
        return []


async def _service(
    port: _FakeXWikiPort,
) -> tuple[XWikiDocumentationSyncService, InMemoryDocumentRepository, XWikiWatermarks, Project]:
    projects = InMemoryProjectRepository()
    project = Project(
        name="ADAS Platform",
        external_refs=[
            ExternalReference(provider="xwiki", external_id="ADAS", external_type="space")
        ],
    )
    await projects.create(project)

    resolver = XWikiProjectResolver(projects=projects)

    watermarks = XWikiWatermarks(watermarks=InMemorySyncWatermarkRepository())
    documents = InMemoryDocumentRepository()
    registry = DefaultParserRegistry()
    registry.register(XWikiSyntaxParser())
    ingestion = DocumentIngestionService(
        documents=documents,
        parser_registry=registry,
        entity_extractor=_NoopEntityExtractor(),
        reference_extractor=_NoopReferenceExtractor(),
        decisions=None,
    )
    service = XWikiDocumentationSyncService(
        resolver=resolver,
        watermarks=watermarks,
        ingestion=ingestion,
        mapping=None,
    )
    return service, documents, watermarks, project


class _NoopEntityExtractor:
    def extract(self, parsed):
        return []


class _NoopReferenceExtractor:
    def extract(self, node):
        return []


async def test_initial_sync_ingests_all_and_stores_watermark() -> None:
    now = datetime.now(UTC)
    port = _FakeXWikiPort(
        {
            "ADAS.Page1": (now - timedelta(hours=3), _artifact("ADAS.Page1")),
            "ADAS.Page2": (now - timedelta(hours=2), _artifact("ADAS.Page2")),
            "ADAS.Page3": (now - timedelta(hours=1), _artifact("ADAS.Page3")),
        }
    )
    service, documents, watermarks, project = await _service(port)

    result = await service.sync_space(port, project, "ADAS")
    assert result.discovered == 3
    assert result.ingested == 3
    assert result.failed == 0
    assert len(await documents.list_by_project(project.id)) == 3
    # Watermark persisted.
    assert await watermarks.since(project.id, "ADAS") is not None


async def test_incremental_sync_only_recent_pages() -> None:
    now = datetime.now(UTC)
    old_page = "ADAS.Old"
    new_page = "ADAS.New"
    port = _FakeXWikiPort(
        {
            old_page: (now - timedelta(days=2), _artifact(old_page)),
            new_page: (now - timedelta(minutes=5), _artifact(new_page)),
        }
    )
    service, documents, watermarks, project = await _service(port)

    # First cycle: everything ingested, watermark at T1.
    first = await service.sync_space(port, project, "ADAS")
    assert first.ingested == 2
    # A page modified before T1 but discovered now must not re-ingest when the
    # fake filters by since; simulate: second cycle returns only the new page.
    since_t1 = now - timedelta(hours=1)
    await watermarks.advance(project.id, "ADAS", synced_at=since_t1)

    second = await service.sync_space(port, project, "ADAS")
    assert second.discovered == 1
    # The only discovered page is the recent one; re-processing its unchanged
    # content is a no-op (idempotent ingestion).
    assert second.ingested == 0
    assert second.unchanged == 1
    assert [
        r.external_id for r in await port.list_changed_documents(since_t1, spaces=["ADAS"])
    ] == [new_page]


async def test_idempotent_reingestion_no_duplicate_versions() -> None:
    """Same page/version twice -> one Document, no duplicate version (doc §14)."""
    now = datetime.now(UTC)
    page_id = "ADAS.Page"
    port = _FakeXWikiPort({page_id: (now, _artifact(page_id))})
    service, documents, watermarks, project = await _service(port)

    await service.sync_space(port, project, "ADAS")
    await service.sync_space(port, project, "ADAS")

    stored = await documents.list_by_project(project.id)
    assert len(stored) == 1
    versions = await documents.list_versions(stored[0].id)
    assert len(versions) == 1


async def test_failure_isolation_blocks_watermark_advance() -> None:
    now = datetime.now(UTC)
    port = _FakeXWikiPort(
        {
            "ADAS.A": (now, _artifact("ADAS.A")),
            "ADAS.B": (now, _artifact("ADAS.B")),
            "ADAS.C": (now, _artifact("ADAS.C")),
        },
        failing={"ADAS.B"},
    )
    service, documents, watermarks, project = await _service(port)

    result = await service.sync_space(port, project, "ADAS")
    assert result.discovered == 3
    assert result.ingested == 2
    assert result.failed == 1
    assert any("fetch boom" in d for d in result.details)
    # Watermark NOT advanced: the failed page stays eligible for retry.
    assert await watermarks.since(project.id, "ADAS") is None


async def test_unmapped_page_blocks_watermark_advance() -> None:
    now = datetime.now(UTC)

    class _UnfilteredPort(_FakeXWikiPort):
        """Discovery without space filtering: an unmapped page can slip in."""

        async def list_changed_documents(
            self,
            since: datetime | None = None,
            *,
            spaces: list[str] | None = None,
        ) -> list[ExternalReference]:
            refs = []
            for page_id, (modified, _) in self._pages.items():
                if since is not None and modified <= since:
                    continue
                refs.append(_ref(page_id))
            return refs

    port = _UnfilteredPort(
        {
            "ADAS.A": (now, _artifact("ADAS.A")),
            "Unknown.Page": (now, _artifact("Unknown.Page")),
        }
    )
    service, _, watermarks, project = await _service(port)

    result = await service.sync_space(port, project, "ADAS")
    assert result.ingested == 1
    assert result.failed == 1
    assert any("unmapped space Unknown" in d for d in result.details)
    assert await watermarks.since(project.id, "ADAS") is None


async def test_initial_empty_discovery_does_not_advance_watermark() -> None:
    """An initial sync that finds nothing must be retried, not skipped."""
    port = _FakeXWikiPort({})
    service, _, watermarks, project = await _service(port)

    result = await service.sync_space(port, project, "ADAS")
    assert result.discovered == 0
    assert await watermarks.since(project.id, "ADAS") is None


async def test_changed_content_creates_new_version() -> None:
    now = datetime.now(UTC)
    page_id = "ADAS.Page"
    first_content = _artifact(page_id, "== Page ==\n\nold body")
    port = _FakeXWikiPort({page_id: (now, first_content)})
    service, documents, watermarks, project = await _service(port)

    first = await service.sync_space(port, project, "ADAS")
    assert first.ingested == 1
    await watermarks.advance(project.id, "ADAS", synced_at=now - timedelta(hours=1))

    # Same page, changed content -> same Document, new DocumentVersion.
    port._pages[page_id] = (now, _artifact(page_id, "== Page ==\n\nnew body"))
    second = await service.sync_space(port, project, "ADAS")
    assert second.ingested == 1
    stored = await documents.list_by_project(project.id)
    assert len(stored) == 1
    assert len(await documents.list_versions(stored[0].id)) == 2
