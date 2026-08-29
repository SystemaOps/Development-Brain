"""DocumentationPort contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from brain.domain.documents import SourceArtifact
from brain.domain.external_reference import ExternalReference
from brain.ports.documentation import DocumentationPort


class DocumentationPortContract:
    @pytest.fixture
    def documentation(self) -> DocumentationPort:
        raise NotImplementedError

    @pytest.fixture
    def documentation_provider(self) -> str:
        return "test"

    def test_adapter_conforms_to_port(self, documentation: DocumentationPort) -> None:
        assert isinstance(documentation, DocumentationPort)

    async def test_fetch_document(
        self, documentation: DocumentationPort, documentation_provider: str
    ) -> None:
        ref = ExternalReference(provider=documentation_provider, external_id="page-1")
        artifact = await documentation.fetch_document(ref)
        assert isinstance(artifact, SourceArtifact)
        assert artifact.provider == documentation_provider

    async def test_list_changed_documents(self, documentation: DocumentationPort) -> None:
        since = datetime.now(UTC) - timedelta(hours=24)
        refs = await documentation.list_changed_documents(since)
        assert isinstance(refs, list)

    async def test_search(self, documentation: DocumentationPort) -> None:
        refs = await documentation.search("login")
        assert isinstance(refs, list)
