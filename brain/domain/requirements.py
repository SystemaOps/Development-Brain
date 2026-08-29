"""Requirement domain.

Requirements support hierarchy (parent/derived), acceptance criteria,
constraints, and provenance to the source that introduced them.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.common import Priority
from brain.domain.external_reference import SourceReference
from brain.domain.identity import ProjectId, RequirementId, new_requirement_id
from brain.domain.work_items import AcceptanceCriterion


class RequirementStatus(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    IMPLEMENTED = "implemented"
    VERIFIED = "verified"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class RequirementSourceType(StrEnum):
    DOCUMENT = "document"
    TICKET = "ticket"
    ADR = "adr"
    MANUAL = "manual"
    DERIVED = "derived"
    INFERRED = "inferred"


class RequirementSource(BaseModel):
    source_type: RequirementSourceType = RequirementSourceType.MANUAL
    source: SourceReference | None = None


class ConstraintKind(StrEnum):
    MUST = "must"
    MUST_NOT = "must_not"
    SHOULD = "should"
    SHOULD_NOT = "should_not"


class Constraint(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    kind: ConstraintKind = ConstraintKind.MUST
    description: str
    scope: str | None = None


class Requirement(BaseModel):
    id: RequirementId = Field(default_factory=new_requirement_id)
    project_id: ProjectId
    key: str | None = None
    title: str
    description: str = ""
    status: RequirementStatus = RequirementStatus.DRAFT
    priority: Priority | None = None
    parent_id: RequirementId | None = None
    derived_from: list[RequirementId] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    source_refs: list[RequirementSource] = Field(default_factory=list)
