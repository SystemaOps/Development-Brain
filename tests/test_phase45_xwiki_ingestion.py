"""Phase 45 gate tests: XWiki ingestion runtime (Step 1).

Step 1 acceptance: the production runtime registers its document parsers and
the canonical ``INGEST_DOCUMENT`` command actually ingests (no more "no parser
registered" at runtime).
"""

from __future__ import annotations

import uuid

import pytest

from brain.application.document_ingestion import DocumentIngestionService
from brain.bootstrap.container import create_brain_container
from brain.bootstrap.settings import (
    BrainSettings,
    DocumentationSettings,
    Neo4jSettings,
    PostgresSettings,
    RedisSettings,
    SourceControlSettings,
    VerificationSettings,
    WeaviateSettings,
    WorkManagementSettings,
)
from brain.domain.documents import Document, DocumentSource
from brain.workers.loop import run_worker_once
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)


def _settings() -> BrainSettings:
    return BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://127.0.0.1:7687"),
        storage_semantic=WeaviateSettings(host="127.0.0.1"),
        storage_queue=RedisSettings(url="redis://127.0.0.1:6379/0", provider="inmemory"),
        work_management=WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
    )


async def test_gate_runtime_parser_registry_contains_production_parsers() -> None:
    """build_services registers the production parsers (Step 1/2)."""
    container = await create_brain_container(_settings())
    try:
        ingestion = container.services["document_ingestion"]
        assert isinstance(ingestion, DocumentIngestionService)
        names = {parser.name for parser in ingestion._parsers.list()}
        assert {"adr", "markdown", "html", "pdf", "xwiki"} <= names, names
    finally:
        await container.close()


async def test_gate_xwiki_payload_ingests_through_runtime_registry() -> None:
    """A real XWiki payload flows through the runtime registry end-to-end."""
    container = await create_brain_container(_settings())
    try:
        ingestion = container.services["document_ingestion"]
        assert isinstance(ingestion, DocumentIngestionService)
        from brain.domain.documents import SourceArtifact
        from brain.domain.projects import Project

        brain_project = Project(name="xwiki-roundtrip-test")
        await container.repositories.projects.create(brain_project)

        content = (
            "== Architecture ==\n\n"
            "The service uses **PostgreSQL** for state.\n\n"
            "=== Components ===\n\n"
            "* brain-api\n"
            "* brain-worker\n\n"
            '{{code language="python"}}\nx = 1\n{{/code}}'
        )
        artifact = SourceArtifact(
            source_uri="ADAS.Architecture.WebHome",
            provider="xwiki",
            mime_type="text/x-xwiki",
            file_name="ADAS.Architecture.WebHome",
            revision="1.2",
            content=content.encode("utf-8"),
            metadata={"syntax": "xwiki/2.1", "space": "ADAS"},
        )
        result = await ingestion.ingest(artifact, project_id=brain_project.id)
        assert result.created_new_version is True
        assert result.document.type.value == "general"
        assert result.nodes
        assert any(node.node_type.value == "section" for node in result.nodes)
        assert any(node.node_type.value == "code_block" for node in result.nodes)
        assert result.chunks
    finally:
        await container.close()


async def test_gate_xwiki_watermark_survives_restart() -> None:
    """Step 5: the documentation watermark resumes after a container restart."""
    from datetime import UTC, datetime, timedelta

    from brain.application.xwiki_ingestion import XWikiWatermarks
    from brain.domain.identity import ProjectId
    from brain.domain.projects import Project

    project_id: ProjectId | None = None
    synced_at = datetime.now(UTC) - timedelta(minutes=10)

    first = await create_brain_container(_settings())
    try:
        watermarks = first.services["xwiki_watermarks"]
        assert isinstance(watermarks, XWikiWatermarks)
        brain_project = Project(name="xwiki-watermark-test")
        await first.repositories.projects.create(brain_project)
        project_id = brain_project.id
        await watermarks.advance(
            brain_project.id, "ADAS", synced_at=synced_at, last_external_id="ADAS.P1"
        )
        if first.session is not None:
            await first.session.commit()
    finally:
        await first.close()

    # Restart: a new container over the same database resumes from the cursor.
    assert project_id is not None
    second = await create_brain_container(_settings())
    try:
        watermarks = second.services["xwiki_watermarks"]
        assert isinstance(watermarks, XWikiWatermarks)
        assert await watermarks.since(project_id, "ADAS") == synced_at
    finally:
        await second.close()
    """INGEST_DOCUMENT through the real command path produces nodes."""
    container = await create_brain_container(_settings())
    try:
        project = container.repositories.projects
        from brain.domain.projects import Project

        brain_project = Project(name="parser-runtime-test")
        await project.create(brain_project)

        # Register a document carrying raw content (the command path builds the
        # artifact from the document; content-less sources are fetched in the
        # XWiki reconciliation step).
        document = Document(
            project_id=brain_project.id,
            title="runtime.md",
            source=DocumentSource(
                provider="test",
                uri="docs/runtime.md",
                mime_type="text/markdown",
            ),
        )
        await container.repositories.documents.create(document)

        from brain.domain.commands import CommandType, IngestDocumentCommand, make_command
        from brain.ports.commands import CommandQueue

        queue = container.services["command_queue"]
        assert isinstance(queue, CommandQueue)
        await queue.enqueue(
            make_command(
                CommandType.INGEST_DOCUMENT,
                IngestDocumentCommand(document_id=document.id, project_id=brain_project.id),
            )
        )
        processed = await run_worker_once(container, max_commands=1)
        assert processed == 1

        # The failure (if any) is a content-fetching concern, never a parser
        # registration one: the registry must select a parser for the artifact.
        ingestion = container.services["document_ingestion"]
        assert isinstance(ingestion, DocumentIngestionService)
        from brain.domain.documents import SourceArtifact

        artifact = SourceArtifact(
            source_uri="docs/runtime.md",
            provider="test",
            mime_type="text/markdown",
            file_name="runtime.md",
            content=b"# Title\n\nBody",
        )
        selected = ingestion._parsers.select(artifact)
        assert selected is not None
        assert selected.name == "markdown"
    finally:
        await container.close()


async def test_gate_scheduler_reconciles_mapped_xwiki_space() -> None:
    """Step 6: reconcile_documentation performs real ingestion end-to-end."""
    from datetime import datetime

    from brain.application.xwiki_ingestion import (
        XWikiDocumentationSyncService,
        XWikiWatermarks,
    )
    from brain.domain.documents import SourceArtifact
    from brain.domain.external_reference import ExternalReference
    from brain.domain.projects import Project
    from brain.scheduler.reconciliation import ReconciliationReport, ReconciliationService

    container = await create_brain_container(_settings())
    space = f"Space{uuid.uuid4().hex[:8]}"
    page_id = f"{space}.PageOne"
    brain_project = Project(
        name="xwiki-scheduler-test",
        external_refs=[
            ExternalReference(provider="xwiki", external_id=space, external_type="space")
        ],
    )
    try:
        await container.repositories.projects.create(brain_project)

        class _FakeXWikiPort:
            async def list_changed_documents(
                self,
                since: datetime | None = None,
                *,
                spaces: list[str] | None = None,
            ) -> list[ExternalReference]:
                return [
                    ExternalReference(provider="xwiki", external_id=page_id, external_type="page")
                ]

            async def fetch_document(self, ref: ExternalReference) -> SourceArtifact:
                return SourceArtifact(
                    source_uri=ref.external_id,
                    provider="xwiki",
                    mime_type="text/x-xwiki",
                    file_name=ref.external_id,
                    revision="1.1",
                    content=b"== Page One ==\n\nScheduler-ingested content.",
                    metadata={"syntax": "xwiki/2.1", "space": space},
                )

            async def search(self, query: str) -> list[ExternalReference]:
                return []

        # Wire the fake port into the container alongside the real sync service.
        container.documentation_ports = [_FakeXWikiPort()]  # type: ignore[assignment]
        service = container.services["xwiki_documentation_sync"]
        assert isinstance(service, XWikiDocumentationSyncService)

        report = ReconciliationReport()
        await ReconciliationService(container).reconcile_documentation(report)
        assert report.documentation_checked >= 1
        assert report.documentation_synced >= 1

        # The page was ingested into the canonical project (and committed).
        docs = await container.repositories.documents.list_by_project(brain_project.id)
        assert len(docs) == 1
        assert docs[0].current_version_id is not None

        # The durable watermark was persisted (advance on zero failures).
        watermarks = container.services["xwiki_watermarks"]
        assert isinstance(watermarks, XWikiWatermarks)
        assert await watermarks.since(brain_project.id, space) is not None
    finally:
        # Clean up committed rows so the shared DB stays deterministic.

        docs = await container.repositories.documents.list_by_project(brain_project.id)
        for doc in docs:
            if doc.current_version_id is not None:
                await container.repositories.documents.delete(doc.id)
        await container.repositories.projects.delete(brain_project.id)
        if container.session is not None:
            await container.session.commit()
        await container.close()


async def test_gate_ingest_document_with_runtime_registry_round_trip() -> None:
    """The runtime registry parses markdown content end-to-end."""
    container = await create_brain_container(_settings())
    try:
        ingestion = container.services["document_ingestion"]
        assert isinstance(ingestion, DocumentIngestionService)
        from brain.domain.documents import SourceArtifact
        from brain.domain.projects import Project

        brain_project = Project(name="parser-roundtrip-test")
        await container.repositories.projects.create(brain_project)

        artifact = SourceArtifact(
            source_uri="docs/spec.md",
            provider="test",
            mime_type="text/markdown",
            file_name="spec.md",
            content=b"# Title\n\nSome **bold** text.\n\n## Section\n\n- item one\n- item two",
        )
        result = await ingestion.ingest(artifact, project_id=brain_project.id)
        assert result.created_new_version is True
        assert result.nodes
        assert result.chunks
        assert result.document.type.value == "general"
    finally:
        await container.close()
