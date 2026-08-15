"""Context engine domain model (Phase 10).

The context engine constructs precise, bounded task context from many sources
(work item, requirements, knowledge graph, code graph, semantic/lexical search,
history, verification feedback).  A :class:`ContextRequest` describes what to
build; retrieval produces :class:`ContextCandidate` items with reasons and
scores; the allocator fills category budgets; the result is a persistent
:class:`ContextCapsule` (Planning / Coding / Verification variants) that can be
evaluated later.

Principle 2.7: every context-building API accepts an explicit token budget.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import (
    ContextCapsuleId,
    ExecutionId,
    ProjectId,
    RepositoryId,
    WorkItemId,
    new_context_capsule_id,
)


class ContextType(StrEnum):
    PLANNING = "planning"
    CODING = "coding"
    VERIFICATION = "verification"


class ContextCategory(StrEnum):
    """Budget allocation categories (Task 10.6)."""

    TASK = "task"
    REQUIREMENTS = "requirements"
    ARCHITECTURE = "architecture"
    SOURCE_CODE = "source_code"
    TESTS = "tests"
    HISTORY = "history"
    INSTRUCTIONS = "instructions"


class RetrievalSource(StrEnum):
    WORK_ITEM = "work_item"
    REQUIREMENT = "requirement"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    CODE_GRAPH = "code_graph"
    SEMANTIC_SEARCH = "semantic_search"
    LEXICAL_SEARCH = "lexical_search"
    GIT_HISTORY = "git_history"
    VERIFICATION_FEEDBACK = "verification_feedback"


class ContextRequest(BaseModel):
    """What the context engine should build (Task 10.1)."""

    work_item_id: WorkItemId
    project_id: ProjectId | None = None
    repository_id: RepositoryId | None = None
    revision: str | None = None
    context_type: ContextType = ContextType.CODING
    preferred_token_budget: int = 8000
    max_total_tokens: int = 32000
    executor_capability: str = "coding"
    risk: str = "low"
    include_history: bool = True
    include_verification_feedback: bool = True


class ContextCandidate(BaseModel):
    """One item considered for inclusion (Task 10.2)."""

    entity_id: uuid.UUID
    entity_type: str
    content: str
    reason: str = ""
    retrieval_source: RetrievalSource = RetrievalSource.SEMANTIC_SEARCH
    relevance_score: float = 0.0
    trust_score: float = 0.5
    freshness: float = 0.5
    token_estimate: int = 0
    category: ContextCategory = ContextCategory.SOURCE_CODE
    metadata: dict[str, object] = Field(default_factory=dict)


class BudgetAllocation(BaseModel):
    """Per-category token budget (Task 10.6)."""

    category: ContextCategory
    allocated_tokens: int
    used_tokens: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.allocated_tokens - self.used_tokens)


class ContextCapsule(BaseModel):
    """The bounded, explainable output of the context engine (Task 10.7)."""

    id: ContextCapsuleId = Field(default_factory=new_context_capsule_id)
    version: str = "1.0"
    work_item_id: WorkItemId
    context_type: ContextType = ContextType.CODING
    request: ContextRequest
    repository_id: RepositoryId | None = None
    revision: str | None = None
    candidates: list[ContextCandidate] = Field(default_factory=list)
    allocations: list[BudgetAllocation] = Field(default_factory=list)
    total_tokens: int = 0
    model_budget_tokens: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    linked_execution_ids: list[ExecutionId] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)

    @property
    def is_within_budget(self) -> bool:
        return self.total_tokens <= self.model_budget_tokens


class PlanningContextCapsule(ContextCapsule):
    context_type: ContextType = ContextType.PLANNING


class CodingContextCapsule(ContextCapsule):
    context_type: ContextType = ContextType.CODING


class VerificationContextCapsule(ContextCapsule):
    context_type: ContextType = ContextType.VERIFICATION


__all__ = [
    "BudgetAllocation",
    "CodingContextCapsule",
    "ContextCandidate",
    "ContextCategory",
    "ContextCapsule",
    "ContextRequest",
    "ContextType",
    "PlanningContextCapsule",
    "RetrievalSource",
    "VerificationContextCapsule",
]
