"""Phase 35 golden tests and completion gate.

XWiki enriches the Brain as an optional documentation source but can be
removed or disabled without impacting the core system: pages normalize to
canonical artifacts, changes emit DocumentChanged, spaces map via
ExternalReference, and only selected observations may be published to XWiki.
"""

from __future__ import annotations

import json
import urllib.request
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from brain.adapters.documentation.xwiki import XWikiDocumentationAdapter
from brain.adapters.documentation.xwiki_http import XWikiHTTPTransport
from brain.application.xwiki_sync import (
    XWikiMappingService,
    XWikiPublicationPolicy,
)
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
from brain.domain.documents import DocumentType
from brain.domain.observations import (
    Observation,
    ObservationType,
    ObservationVisibility,
)
from brain.domain.projects import ProjectId
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@localhost:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)


def _settings(documentation: DocumentationSettings | None = None) -> BrainSettings:
    return BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://localhost:7687"),
        storage_semantic=WeaviateSettings(host="localhost"),
        storage_queue=RedisSettings(url="redis://localhost:6379/0"),
        work_management=WorkManagementSettings(enabled=False),
        documentation=documentation
        or DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
    )


def test_mapping_service_uses_external_reference_identity() -> None:
    """XWiki IDs are stored as ExternalReference, never internal ids (35.5)."""
    service = XWikiMappingService(wiki="xwiki")
    ref = service.ref("xwiki/Main/Home")
    assert ref.provider == "xwiki"
    assert ref.external_id == "xwiki/Main/Home"
    assert ref.namespace == "xwiki"


def test_mapping_service_normalizes_page_to_artifact() -> None:
    """An XWiki page normalizes to a canonical SourceArtifact (35.3)."""
    service = XWikiMappingService(wiki="xwiki")
    artifact = service.to_source_artifact(
        {
            "id": "xwiki/Main/Home",
            "title": "Home",
            "content": "<p>Hello</p>",
            "version": "3",
            "parent": "xwiki/Main",
        }
    )
    assert artifact.provider == "xwiki"
    assert artifact.revision == "3"
    assert artifact.mime_type == "text/html"
    assert artifact.content == b"<p>Hello</p>"
    assert artifact.metadata["wiki"] == "xwiki"


def test_mapping_service_infers_document_type() -> None:
    service = XWikiMappingService()
    assert service.document_type_for_page({"id": "xwiki/Space/ADR-001"}) == DocumentType.ADR
    assert service.document_type_for_page({"id": "xwiki/Space/REQ-7"}) == DocumentType.REQUIREMENTS
    assert (
        service.document_type_for_page({"id": "xwiki/Space/Architecture"})
        == DocumentType.ARCHITECTURE
    )
    assert service.document_type_for_page({"id": "xwiki/Space/Other"}) == DocumentType.GENERAL


async def test_changed_page_emits_document_changed_event() -> None:
    """Changed pages normalize to DocumentChanged (35.4)."""
    from brain.adapters.in_memory.event_bus import InMemoryEventBus

    bus = InMemoryEventBus()
    service = XWikiMappingService(wiki="xwiki", event_bus=bus)
    ref = service.ref("xwiki/Main/Home")
    since = datetime.now(UTC)
    await service.emit_changed(ref, since=since)
    assert len(bus.published) == 1
    assert bus.published[0].event_type.value == "document_changed"
    assert bus.published[0].payload["external_id"] == "xwiki/Main/Home"


def test_publication_policy_selective() -> None:
    """Not every observation is published to XWiki (35.6)."""
    project_id = ProjectId(uuid.uuid4())

    def _obs(observation_type: ObservationType) -> Observation:
        return Observation(
            project_id=project_id,
            observation_type=observation_type,
            title="t",
            visibility=ObservationVisibility.TEAM,
        )

    assert XWikiPublicationPolicy.may_publish(_obs(ObservationType.ARCHITECTURE_VIOLATION))
    assert XWikiPublicationPolicy.may_publish(_obs(ObservationType.CONFLICT))
    assert not XWikiPublicationPolicy.may_publish(_obs(ObservationType.DISCOVERY))
    assert not XWikiPublicationPolicy.may_publish(_obs(ObservationType.VERIFICATION_PASS))


def test_publication_policy_internal_never_published() -> None:
    project_id = ProjectId(uuid.uuid4())
    observation = Observation(
        project_id=project_id,
        observation_type=ObservationType.CONFLICT,
        title="t",
    )
    # Default visibility is internal.
    assert observation.visibility.value == "internal"
    assert not XWikiPublicationPolicy.may_publish(observation)


async def test_adapter_fetch_via_http_transport() -> None:
    """The adapter fetches pages through the HTTP transport (35.2)."""
    fake = json.dumps(
        {
            "title": "Home",
            "content": "<p>Hello</p>",
            "version": {"number": "4"},
            "parent": {"pageFullReference": "xwiki/Main"},
            "id": "xwiki/Main/Home",
        }
    ).encode("utf-8")

    class _FakeResponse:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return self._data

    def _fake_urlopen(request: object, timeout: int) -> _FakeResponse:
        del request, timeout
        return _FakeResponse(fake)

    adapter = XWikiDocumentationAdapter(transport=XWikiHTTPTransport(base_url="http://xwiki:8080"))
    with patch.object(urllib.request, "urlopen", _fake_urlopen):
        artifact = await adapter.fetch_document(adapter._ref("xwiki/Main/Home"))
    assert artifact.provider == "xwiki"
    assert artifact.revision == "4"


async def test_container_reports_xwiki_disabled() -> None:
    """XWiki disabled: Brain ready, capability DISABLED, no documentation ports."""
    container = await create_brain_container(_settings())
    try:
        assert container.capabilities()["documentation_xwiki"] == "DISABLED"
        assert container.is_ready() is True
        assert container.documentation_ports == []
    finally:
        await container.close()


async def test_container_builds_xwiki_port_when_enabled() -> None:
    """XWiki enabled with a URL: the documentation port is built."""
    container = await create_brain_container(
        _settings(
            DocumentationSettings(
                git_enabled=False,
                xwiki_enabled=True,
                xwiki_url="http://xwiki:8080",
            )
        )
    )
    try:
        assert container.capabilities()["documentation_xwiki"] == "AVAILABLE"
        assert container.is_ready() is True
        assert len(container.documentation_ports) == 1
        assert container.services["xwiki_mapping"] is not None
    finally:
        await container.close()
