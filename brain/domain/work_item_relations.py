"""Work-item relation domain model.

Provider work-package relations (parent-child, blocks, relates-to, precedes,
follows) are persisted canonically in ``work_item_relations`` and projected
into the knowledge graph with the matching ``RelationType`` edges.  Relations
always reference canonical ``WorkItemId`` values; the provider identity is
kept on the optional external reference.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import (
    WorkItemId,
    WorkItemRelationId,
    new_work_item_relation_id,
)


class WorkItemRelationType(StrEnum):
    PARENT_OF = "parent_of"
    BLOCKS = "blocks"
    RELATES_TO = "relates_to"
    PRECEDES = "precedes"
    FOLLOWS = "follows"


class WorkItemRelation(BaseModel):
    id: WorkItemRelationId = Field(default_factory=new_work_item_relation_id)
    source_work_item_id: WorkItemId
    target_work_item_id: WorkItemId
    relation_type: WorkItemRelationType
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    external_refs: list[ExternalReference] = Field(default_factory=list)


__all__ = ["WorkItemRelation", "WorkItemRelationType"]
