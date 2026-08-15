"""SemanticIndex contract."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.identity import new_project_id
from brain.domain.knowledge import SemanticRecord
from brain.ports.semantic_index import SemanticIndex


class SemanticIndexContract:
    @pytest.fixture
    def semantic_index(self) -> SemanticIndex:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, semantic_index: SemanticIndex) -> None:
        assert isinstance(semantic_index, SemanticIndex)

    async def test_index_and_search(self, semantic_index: SemanticIndex) -> None:
        await semantic_index.index(
            [
                SemanticRecord(
                    entity_id=uuid.uuid4(),
                    entity_type="DocumentNode",
                    text="The refresh token expires after fifteen minutes.",
                ),
                SemanticRecord(
                    entity_id=uuid.uuid4(),
                    entity_type="DocumentNode",
                    text="Billing is processed at the end of every month.",
                ),
            ]
        )
        results = await semantic_index.search("refresh token expiry", {}, limit=5)
        assert len(results) == 1
        assert "refresh token" in results[0].text

    async def test_search_respects_project_filter(self, semantic_index: SemanticIndex) -> None:
        project_a = new_project_id()
        project_b = new_project_id()
        await semantic_index.index(
            [
                SemanticRecord(
                    entity_id=uuid.uuid4(),
                    entity_type="DocumentNode",
                    text="authentication happens here",
                    project_id=project_a,
                ),
                SemanticRecord(
                    entity_id=uuid.uuid4(),
                    entity_type="DocumentNode",
                    text="authentication happens here",
                    project_id=project_b,
                ),
            ]
        )
        results = await semantic_index.search("authentication", {"project_id": project_a}, limit=5)
        assert len(results) == 1
        assert results[0].project_id == project_a

    async def test_delete_removes_records(self, semantic_index: SemanticIndex) -> None:
        record = SemanticRecord(
            entity_id=uuid.uuid4(), entity_type="DocumentNode", text="unique terminology xyzzy"
        )
        await semantic_index.index([record])
        assert await semantic_index.search("xyzzy", {}, limit=5)
        await semantic_index.delete([record.record_id])
        assert await semantic_index.search("xyzzy", {}, limit=5) == []
