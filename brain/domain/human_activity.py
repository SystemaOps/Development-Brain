"""Human activity projection domain model (Phase 27).

Selected observations are projected into configured human tools through
:class:`HumanActivityPort`.  :class:`HumanActivityReference` tracks one
published activity/comment so projection is idempotent (a retry must not
create a duplicate human comment).  The model is provider-neutral: external
comment IDs are stored as references, never as brain identities.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ObservationId


class ProjectionStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"
    SKIPPED = "skipped"


class HumanActivityReference(BaseModel):
    """One projected observation in a human tool (Task 27.3)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    observation_id: ObservationId
    provider: str
    target: ExternalReference
    external_activity_id: str | None = None
    status: ProjectionStatus = ProjectionStatus.PENDING
    published_at: datetime | None = None
    error: str | None = None


class HumanFeedback(BaseModel):
    """A human reply intended as Brain feedback (Task 27.7)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    author: str
    provider: str
    external_comment_id: str
    work_item_id: uuid.UUID | None = None
    message: str = ""
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


__all__ = [
    "HumanActivityReference",
    "HumanFeedback",
    "ProjectionStatus",
]
