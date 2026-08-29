"""Knowledge graph reconciliation model (Task 8.6).

Multiple evidence claims can support one conceptual relation (e.g.
``payment-service DEPENDS_ON redis`` with evidence from Docker Compose, source
imports, and runtime traces).  These claims are never collapsed into a single
silent answer: the strongest claim wins for display, while the rest are
preserved so disagreement stays visible.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from brain.domain.graph_schema import RelationType
from brain.domain.knowledge import KnowledgeEvidence


class RelationClaim(BaseModel):
    """One evidence-backed claim for a conceptual relation."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    relation_type: RelationType
    subject_key: str
    object_key: str
    value: str = "present"
    evidence: list[KnowledgeEvidence] = Field(default_factory=list)

    @property
    def confidence(self) -> float:
        if not self.evidence:
            return 0.0
        return max(_score(e) for e in self.evidence)

    @property
    def origin_rank(self) -> int:
        """Declared beats observed beats discovered beats inferred."""
        order = {"declared": 0, "observed": 1, "discovered": 2, "inferred": 3}
        ranks = [
            order[origin] for origin in (_origin(e) for e in self.evidence) if origin is not None
        ]
        return min(ranks) if ranks else 4


class ReconciledRelation(BaseModel):
    """The winning view of one conceptual relation plus its full evidence."""

    relation_type: RelationType
    subject_key: str
    object_key: str
    value: str
    confidence: float
    origin: str
    claims: list[RelationClaim] = Field(default_factory=list)


class GraphReconciler:
    """Pick the strongest claim per conceptual relation without losing the rest."""

    def reconcile(self, claims: list[RelationClaim]) -> list[ReconciledRelation]:
        grouped: dict[tuple[str, RelationType, str], list[RelationClaim]] = {}
        for claim in claims:
            key = (claim.subject_key, claim.relation_type, claim.object_key)
            grouped.setdefault(key, []).append(claim)

        reconciled: list[ReconciledRelation] = []
        for _key, group in grouped.items():
            winner = min(group, key=lambda c: (c.origin_rank, -c.confidence))
            origin = _origin(winner.evidence[0]) if winner.evidence else "unknown"
            reconciled.append(
                ReconciledRelation(
                    relation_type=winner.relation_type,
                    subject_key=winner.subject_key,
                    object_key=winner.object_key,
                    value=winner.value,
                    confidence=winner.confidence,
                    origin=origin or "unknown",
                    claims=group,
                )
            )
        return reconciled


def _score(evidence: KnowledgeEvidence) -> float:
    confidence = evidence.confidence
    return confidence.score() if hasattr(confidence, "score") else float(confidence)


def _origin(evidence: KnowledgeEvidence) -> str | None:
    origin = evidence.origin
    if origin is None:
        return None
    return origin.value if hasattr(origin, "value") else str(origin)


__all__ = ["GraphReconciler", "ReconciledRelation", "RelationClaim"]
