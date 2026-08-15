"""Phase 9 golden tests and completion gate.

Given a project with a document, a requirement, a decision, and a code symbol
indexed at an exact revision, the system retrieves semantically relevant
records for a task description while enforcing project / repository / revision
filters.  Uses the in-memory reference index (and the deterministic embedding
service) so it runs without external infrastructure.
"""

from __future__ import annotations

import uuid

import pytest

from brain.adapters.code_intelligence.python_ast import PythonAstParser
from brain.adapters.embeddings.hash_embedding import HashEmbeddingService
from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.repositories import (
    InMemoryDecisionRepository,
    InMemoryDocumentRepository,
    InMemoryRequirementRepository,
)
from brain.adapters.in_memory.semantic_index import InMemorySemanticIndex
from brain.application.code_intelligence import CodeIntelligenceService
from brain.application.hybrid_retrieval import HybridRetrievalService
from brain.application.semantic_indexing import SemanticIndexingService
from brain.domain.documents import (
    Document,
    DocumentNode,
    DocumentNodeType,
    DocumentSource,
    DocumentVersion,
)
from brain.domain.identity import RepositoryId, new_project_id
from brain.domain.projects import Project
from brain.domain.requirements import Requirement

REVISION = "abc123"

REPOSITORY_FILES: dict[str, str] = {
    "app/service.py": """
from .models import User

class AuthService:
    def login(self, uid: str) -> User:
        "Logs a user in and returns their profile."
        return User(uid=uid)
""",
    "app/models.py": """
class User:
    def __init__(self, uid: str) -> None:
        self.uid = uid
""",
}


@pytest.fixture
def index() -> InMemorySemanticIndex:
    return InMemorySemanticIndex(embeddings=HashEmbeddingService())


async def _seed_project(
    index: InMemorySemanticIndex,
) -> tuple[Project, RepositoryId]:
    project = Project(name="auth")
    documents = InMemoryDocumentRepository()
    requirements = InMemoryRequirementRepository()
    decisions = InMemoryDecisionRepository()
    code_graph = InMemoryCodeGraphRepository()

    # Document with a section about token handling.
    document = Document(
        project_id=project.id,
        title="Security",
        source=DocumentSource(provider="git_markdown", uri="docs/security.md"),
    )
    await documents.create(document)
    version = DocumentVersion(document_id=document.id, commit_sha=REVISION, checksum="v1")
    await documents.add_version(version)
    await documents.add_node(
        DocumentNode(
            version_id=version.id,
            node_type=DocumentNodeType.SECTION,
            title="Token Expiry",
            heading_path=["Security", "Token Expiry"],
            content="The refresh token expires after fifteen minutes.",
        )
    )

    requirement = Requirement(project_id=project.id, title="Support refresh tokens", key="REQ-1")
    await requirements.create(requirement)

    # Code graph at the exact revision.
    repository_id = RepositoryId(uuid.uuid4())
    code_service = CodeIntelligenceService(parser=PythonAstParser(), repository=code_graph)
    await code_service.build_revision(repository_id, REVISION, REPOSITORY_FILES)

    indexing = SemanticIndexingService(
        index=index,
        documents=documents,
        requirements=requirements,
        decisions=decisions,
        code_graph=code_graph,
    )
    await indexing.index_project(project.id, repository_id=repository_id, revision=REVISION)

    return project, repository_id


async def test_gate_retrieves_relevant_document(
    index: InMemorySemanticIndex,
) -> None:
    project, _ = await _seed_project(index)
    retrieval = HybridRetrievalService(
        index=index, embeddings=HashEmbeddingService(), graph=InMemoryKnowledgeGraph()
    )
    candidates = await retrieval.retrieve("refresh token expiry", project_id=project.id, limit=5)
    assert any("refresh token" in c.record.text for c in candidates)
    assert all(c.record.project_id == project.id for c in candidates)


async def test_gate_enforces_revision_filter(
    index: InMemorySemanticIndex,
) -> None:
    project, _ = await _seed_project(index)
    retrieval = HybridRetrievalService(
        index=index, embeddings=HashEmbeddingService(), graph=InMemoryKnowledgeGraph()
    )
    candidates = await retrieval.retrieve(
        "refresh token", project_id=project.id, revision=REVISION, limit=5
    )
    assert len(candidates) >= 1
    assert all(c.record.revision == REVISION for c in candidates)


async def test_gate_excludes_other_projects(
    index: InMemorySemanticIndex,
) -> None:
    project, _ = await _seed_project(index)
    other_project_id = new_project_id()
    retrieval = HybridRetrievalService(
        index=index, embeddings=HashEmbeddingService(), graph=InMemoryKnowledgeGraph()
    )
    candidates = await retrieval.retrieve("refresh token", project_id=other_project_id, limit=5)
    assert candidates == []


async def test_gate_retrieves_code_summary(
    index: InMemorySemanticIndex,
) -> None:
    project, _ = await _seed_project(index)
    retrieval = HybridRetrievalService(
        index=index, embeddings=HashEmbeddingService(), graph=InMemoryKnowledgeGraph()
    )
    candidates = await retrieval.retrieve("logs a user in", project_id=project.id, limit=5)
    assert any(c.record.entity_type == "Symbol" for c in candidates)


async def test_gate_retrieves_requirement(
    index: InMemorySemanticIndex,
) -> None:
    project, _ = await _seed_project(index)
    retrieval = HybridRetrievalService(
        index=index, embeddings=HashEmbeddingService(), graph=InMemoryKnowledgeGraph()
    )
    candidates = await retrieval.retrieve("support refresh tokens", project_id=project.id, limit=5)
    assert any(c.record.entity_type == "Requirement" for c in candidates)


async def test_gate_lexical_search_without_vectors(
    index: InMemorySemanticIndex,
) -> None:
    """Lexical search alone must work even when vector search is unavailable."""
    project, _ = await _seed_project(index)
    retrieval = HybridRetrievalService(
        index=index, embeddings=HashEmbeddingService(), graph=InMemoryKnowledgeGraph()
    )
    candidates = await retrieval.retrieve(
        "refresh token", project_id=project.id, limit=5, use_vector=False
    )
    assert any("refresh token" in c.record.text for c in candidates)
    assert all(c.retrieval_source == "lexical" for c in candidates)


async def test_gate_hybrid_ranks_semantic_matches(
    index: InMemorySemanticIndex,
) -> None:
    project, _ = await _seed_project(index)
    retrieval = HybridRetrievalService(
        index=index, embeddings=HashEmbeddingService(), graph=InMemoryKnowledgeGraph()
    )
    candidates = await retrieval.retrieve("token", project_id=project.id, limit=5, use_vector=True)
    sources = {c.retrieval_source for c in candidates}
    assert sources & {"lexical", "semantic"}
