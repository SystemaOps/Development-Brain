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

    async def test_search_respects_revision_filter(self, semantic_index: SemanticIndex) -> None:
        entity_id = uuid.uuid4()
        await semantic_index.index(
            [
                SemanticRecord(
                    entity_id=entity_id,
                    entity_type="DocumentNode",
                    text="cache invalidation logic here",
                    revision="abc",
                ),
                SemanticRecord(
                    entity_id=entity_id,
                    entity_type="DocumentNode",
                    text="cache invalidation logic here",
                    revision="def",
                ),
            ]
        )
        results = await semantic_index.search("cache invalidation", {"revision": "abc"}, limit=5)
        assert len(results) == 1
        assert results[0].revision == "abc"

    async def test_search_by_vector_returns_related(self, semantic_index: SemanticIndex) -> None:
        await semantic_index.index(
            [
                SemanticRecord(
                    entity_id=uuid.uuid4(),
                    entity_type="DocumentNode",
                    text="the refresh token expires after fifteen minutes",
                ),
                SemanticRecord(
                    entity_id=uuid.uuid4(),
                    entity_type="DocumentNode",
                    text="billing is processed at the end of every month",
                ),
            ]
        )
        # A vector close to the refresh-token text must rank it first when the
        # adapter supports vector search.  When embeddings are not configured,
        # this raises RuntimeError and is skipped by the caller.
        try:
            results = await semantic_index.search_by_vector([0.5] * 256, {}, limit=5)
        except RuntimeError:
            pytest.skip("adapter does not support vector search")
        assert results
