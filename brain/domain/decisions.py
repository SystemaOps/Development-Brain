"""Architecture and engineering decisions.

Decisions survive beyond the conversation that created them and are stored as
first-class entities with context, alternatives, and consequences.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.external_reference import ExternalReference, SourceReference
from brain.domain.identity import DecisionId, ProjectId, new_decision_id


class DecisionStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


class Decision(BaseModel):
    id: DecisionId = Field(default_factory=new_decision_id)
    project_id: ProjectId
    title: str
    context: str = ""
    decision: str = ""
    alternatives: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    status: DecisionStatus = DecisionStatus.PROPOSED
    source_refs: list[SourceReference] = Field(default_factory=list)
    external_refs: list[ExternalReference] = Field(default_factory=list)
