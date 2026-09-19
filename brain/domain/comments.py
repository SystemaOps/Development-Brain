"""Comment domain model.

Canonical comments extracted from work-management providers (OpenProject
activities, Jira comments, ...).  A Comment is a first-class entity so that
historical context and live human feedback stay distinguishable: bootstrap
imports comments as context only, while new live comments normalize to
``HumanFeedbackReceived``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import (
    ActorId,
    CommentId,
    WorkItemId,
    new_comment_id,
)


class CommentKind(StrEnum):
    """Whether a comment is historical context or live human feedback."""

    CONTEXT = "context"
    FEEDBACK = "feedback"


class Comment(BaseModel):
    id: CommentId = Field(default_factory=new_comment_id)
    work_item_id: WorkItemId
    author_id: ActorId | None = None
    author_name: str | None = None
    text: str
    kind: CommentKind = CommentKind.CONTEXT
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    external_refs: list[ExternalReference] = Field(default_factory=list)


__all__ = ["Comment", "CommentKind"]
