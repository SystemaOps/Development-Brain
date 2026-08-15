"""Domain unit tests for knowledge provenance types."""

from __future__ import annotations

from brain.domain.knowledge import (
    DiscoveryMethod,
    KnowledgeConfidence,
    KnowledgeEvidence,
    KnowledgeOrigin,
    RevisionScope,
)


def test_confidence_scores_are_ordered() -> None:
    assert KnowledgeConfidence.VERY_LOW.score() < KnowledgeConfidence.LOW.score()
    assert KnowledgeConfidence.LOW.score() < KnowledgeConfidence.MEDIUM.score()
    assert KnowledgeConfidence.MEDIUM.score() < KnowledgeConfidence.HIGH.score()
    assert KnowledgeConfidence.HIGH.score() < KnowledgeConfidence.VERY_HIGH.score()


def test_evidence_origins() -> None:
    evidence = KnowledgeEvidence(
        source_type="pytest",
        discovery_method=DiscoveryMethod.TEST_OBSERVATION,
        origin=KnowledgeOrigin.OBSERVED,
        confidence=KnowledgeConfidence.VERY_HIGH,
    )
    assert evidence.origin == KnowledgeOrigin.OBSERVED
    assert evidence.discovery_method == DiscoveryMethod.TEST_OBSERVATION
    assert evidence.confidence == KnowledgeConfidence.VERY_HIGH


def test_revision_scope_carries_version_context() -> None:
    scope = RevisionScope(
        branch="feature/login",
        commit_sha="0d6124d",
        source_path="services/auth.py",
    )
    assert scope.commit_sha == "0d6124d"
    assert scope.branch == "feature/login"


def test_all_discovery_methods_are_distinct() -> None:
    methods = set(DiscoveryMethod)
    assert len(methods) == len(DiscoveryMethod)
    assert DiscoveryMethod.HUMAN_DECLARED in methods
    assert DiscoveryMethod.LLM_INFERENCE in methods
