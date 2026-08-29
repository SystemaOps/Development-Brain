"""Knowledge provenance: how the brain knows what it knows.

Facts are separated into DECLARED / DISCOVERED / OBSERVED / INFERRED with
distinct trust levels, and every fact can carry a revision scope so knowledge
stays tied to a repository state instead of floating timelessly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import ProjectId, RepositoryId


class KnowledgeOrigin(StrEnum):
    DECLARED = "declared"
    DISCOVERED = "discovered"
    OBSERVED = "observed"
    INFERRED = "inferred"


class DiscoveryMethod(StrEnum):
    HUMAN_DECLARED = "human_declared"
    CATALOG_IMPORT = "catalog_import"
    DOCUMENT_PARSE = "document_parse"
    AST_STATIC_ANALYSIS = "ast_static_analysis"
    MANIFEST_ANALYSIS = "manifest_analysis"
    LLM_INFERENCE = "llm_inference"
    RUNTIME_TRACE = "runtime_trace"
    TEST_OBSERVATION = "test_observation"
    GIT_HISTORY = "git_history"


class KnowledgeConfidence(StrEnum):
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"

    def score(self) -> float:
        return {
            KnowledgeConfidence.VERY_LOW: 0.1,
            KnowledgeConfidence.LOW: 0.3,
            KnowledgeConfidence.MEDIUM: 0.5,
            KnowledgeConfidence.HIGH: 0.8,
            KnowledgeConfidence.VERY_HIGH: 0.95,
        }[self]


class RevisionScope(BaseModel):
    """The repository state a piece of knowledge is valid for."""

    repository_id: RepositoryId | None = None
    branch: str | None = None
    commit_sha: str | None = None
    source_path: str | None = None
    content_hash: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class KnowledgeEvidence(BaseModel):
    """Evidence backing a knowledge fact or relationship."""

    source_type: str
    source_id: str | None = None
    discovery_method: DiscoveryMethod = DiscoveryMethod.LLM_INFERENCE
    origin: KnowledgeOrigin = KnowledgeOrigin.INFERRED
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    confidence: KnowledgeConfidence = KnowledgeConfidence.MEDIUM
    commit_sha: str | None = None
    revision_scope: RevisionScope | None = None


class SemanticRecord(BaseModel):
    """Canonical unit stored in the semantic index.

    The semantic index is an index layer, never the source of truth.
    """

    record_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    entity_id: uuid.UUID
    entity_type: str
    text: str
    project_id: ProjectId | None = None
    repository_id: RepositoryId | None = None
    revision: str | None = None
    source: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
