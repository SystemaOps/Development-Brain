"""Unit tests for Phase 9: lexical search, indexing, hybrid retrieval."""

from __future__ import annotations

import uuid

from brain.adapters.embeddings.hash_embedding import HashEmbeddingService
from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.repositories import (
    InMemoryDecisionRepository,
    InMemoryDocumentRepository,
    InMemoryRequirementRepository,
)
from brain.adapters.in_memory.semantic_index import InMemorySemanticIndex
from brain.application.hybrid_retrieval import HybridRetrievalService
from brain.application.lexical_search import LexicalSearchService
from brain.application.semantic_indexing import SemanticIndexingService
from brain.domain.decisions import Decision
from brain.domain.documents import (
    Document,
    DocumentNode,
    DocumentNodeType,
    DocumentSource,
    DocumentVersion,
)
from brain.domain.graph_schema import GraphLabel
from brain.domain.identity import (
    DocumentVersionId,
    RepositoryId,
)
from brain.domain.knowledge import SemanticRecord
from brain.domain.projects import Project
from brain.domain.requirements import Requirement
from brain.ports.knowledge_graph import GraphEntity


def _document_node(version_id: DocumentVersionId, content: str) -> DocumentNode:
    return DocumentNode(
        version_id=version_id,
        node_type=DocumentNodeType.SECTION,
        title="section",
        content=content,
        heading_path=["section"],
    )


async def test_lexical_search_bm25_ranks_relevant_first() -> None:
    corpus = [
        SemanticRecord(
            entity_id=uuid.uuid4(), entity_type="DocumentNode", text="refresh token expires quickly"
        ),
        SemanticRecord(
            entity_id=uuid.uuid4(), entity_type="DocumentNode", text="billing at end of month"
        ),
    ]
    results = LexicalSearchService().search(corpus, "refresh token expiry", limit=5)
    assert len(results) == 1
    assert "refresh token" in results[0][0].text


async def test_lexical_search_empty_corpus() -> None:
    assert LexicalSearchService().search([], "anything", limit=5) == []


async def test_indexing_service_indexes_documents_requirements_decisions() -> None:
    project = Project(name="auth")
    documents = InMemoryDocumentRepository()
    requirements = InMemoryRequirementRepository()
    decisions = InMemoryDecisionRepository()
    code_graph = InMemoryCodeGraphRepository()
    index = InMemorySemanticIndex(embeddings=HashEmbeddingService())

    document = Document(
        project_id=project.id,
        title="Arch",
        source=DocumentSource(provider="git_markdown", uri="arch.md"),
    )
    await documents.create(document)
    version = DocumentVersion(
        document_id=document.id, repository_id=None, commit_sha="abc", checksum="abc123"
    )
    await documents.add_version(version)
    node = _document_node(version.id, "The system MUST support login.")
    await documents.add_node(node)

    requirement = Requirement(project_id=project.id, title="Login support", key="REQ-1")
    await requirements.create(requirement)
    decision = Decision(project_id=project.id, title="Use JWT")
    await decisions.create(decision)

    service = SemanticIndexingService(
        index=index,
        documents=documents,
        requirements=requirements,
        decisions=decisions,
        code_graph=code_graph,
    )
    result = await service.index_project(project.id)
    assert result.records

    entity_types = {r.entity_type for r in result.records}
    assert "DocumentNode" in entity_types
    assert "Requirement" in entity_types
    assert "Decision" in entity_types

    hits = await index.search("login support", {}, limit=10)
    assert any(r.entity_type == "Requirement" for r in hits)


async def test_indexing_indexes_code_summaries() -> None:
    project = Project(name="auth")
    repository_id = uuid.uuid4()
    from brain.domain.code_intelligence import Symbol, SymbolIdentity, SymbolKind, SymbolLocation

    symbol = Symbol(
        identity=SymbolIdentity(
            repository_id=RepositoryId(repository_id),
            revision="abc",
            module="app.service",
            qualified_name="app.service.AuthService.login",
            kind=SymbolKind.METHOD,
        ),
        name="login",
        path="app/service.py",
        kind=SymbolKind.METHOD,
        location=SymbolLocation(path="app/service.py", start_line=1),
        qualified_name="app.service.AuthService.login",
        parameters=["uid: str"],
        return_annotation="User",
        docstring="Logs a user in.",
    )
    code_graph = InMemoryCodeGraphRepository()
    await code_graph.save_symbols([symbol])

    index = InMemorySemanticIndex(embeddings=HashEmbeddingService())
    service = SemanticIndexingService(
        index=index,
        documents=InMemoryDocumentRepository(),
        requirements=InMemoryRequirementRepository(),
        decisions=InMemoryDecisionRepository(),
        code_graph=code_graph,
    )
    await service.index_project(
        project.id, repository_id=RepositoryId(repository_id), revision="abc"
    )
    hits = await index.search("log a user in", {}, limit=10)
    assert any(r.entity_type == "Symbol" for r in hits)
    assert any("AuthService.login" in r.text for r in hits)


async def test_hybrid_retrieval_combines_signals() -> None:
    project = Project(name="auth")
    index = InMemorySemanticIndex(embeddings=HashEmbeddingService())
    graph = InMemoryKnowledgeGraph()

    record = SemanticRecord(
        entity_id=uuid.uuid4(),
        entity_type="DocumentNode",
        text="The refresh token expires after fifteen minutes",
        project_id=project.id,
    )
    await index.index([record])
    await graph.upsert_entities(
        [GraphEntity(id=record.entity_id, label=GraphLabel.DOCUMENT_NODE, project_id=project.id)]
    )

    retrieval = HybridRetrievalService(index=index, embeddings=HashEmbeddingService(), graph=graph)
    candidates = await retrieval.retrieve("refresh token expiry", project_id=project.id, limit=5)
    assert len(candidates) >= 1
    assert candidates[0].record.entity_id == record.entity_id
    assert candidates[0].retrieval_source in {"lexical", "semantic"}


async def test_hybrid_retrieval_respects_project_filter() -> None:
    project_a = Project(name="a")
    project_b = Project(name="b")
    index = InMemorySemanticIndex(embeddings=HashEmbeddingService())
    graph = InMemoryKnowledgeGraph()

    await index.index(
        [
            SemanticRecord(
                entity_id=uuid.uuid4(),
                entity_type="DocumentNode",
                text="cache invalidation logic here",
                project_id=project_a.id,
            ),
            SemanticRecord(
                entity_id=uuid.uuid4(),
                entity_type="DocumentNode",
                text="cache invalidation logic here",
                project_id=project_b.id,
            ),
        ]
    )
    retrieval = HybridRetrievalService(index=index, embeddings=HashEmbeddingService(), graph=graph)
    candidates = await retrieval.retrieve("cache invalidation", project_id=project_a.id, limit=5)
    assert all(c.record.project_id == project_a.id for c in candidates)


async def test_hybrid_retrieval_revision_filter() -> None:
    project = Project(name="auth")
    index = InMemorySemanticIndex(embeddings=HashEmbeddingService())
    graph = InMemoryKnowledgeGraph()
    entity_id = uuid.uuid4()
    await index.index(
        [
            SemanticRecord(
                entity_id=entity_id,
                entity_type="DocumentNode",
                text="authentication logic",
                project_id=project.id,
                revision="abc",
            ),
            SemanticRecord(
                entity_id=entity_id,
                entity_type="DocumentNode",
                text="authentication logic",
                project_id=project.id,
                revision="def",
            ),
        ]
    )
    retrieval = HybridRetrievalService(index=index, embeddings=HashEmbeddingService(), graph=graph)
    candidates = await retrieval.retrieve(
        "authentication", project_id=project.id, revision="abc", limit=5
    )
    assert all(c.record.revision == "abc" for c in candidates)


async def test_embedding_service_is_deterministic() -> None:
    embeddings = HashEmbeddingService(dimensions=64)
    (a,) = await embeddings.embed(["the quick brown fox"])
    (b,) = await embeddings.embed(["the quick brown fox"])
    assert a == b
    assert len(a) == 64
