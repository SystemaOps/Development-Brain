from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class FeedbackKind(StrEnum):
    CHANGE_REQUIREMENT = "CHANGE_REQUIREMENT"
    PLAN_FEEDBACK = "PLAN_FEEDBACK"
    APPROVAL = "APPROVAL"
    REWORK_REQUEST = "REWORK_REQUEST"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CANCEL = "CANCEL"
    UNKNOWN = "UNKNOWN"


class FeedbackEvent(BaseModel):
    kind: FeedbackKind
    source: str
    body: str
    external_id: str | None = None
