from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class EventProcessingStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class EventEnvelope(BaseModel):
    source: str
    event_type: str
    idempotency_key: str | None = None
    occurred_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    external_project_id: str | None = None
    external_work_package_id: str | None = None
    external_comment_id: str | None = None

    @model_validator(mode="after")
    def populate_idempotency_key(self) -> "EventEnvelope":
        if not self.idempotency_key:
            self.idempotency_key = calculate_event_idempotency_key(
                source=self.source,
                event_type=self.event_type,
                external_project_id=self.external_project_id,
                external_work_package_id=self.external_work_package_id,
                external_comment_id=self.external_comment_id,
                payload=self.payload,
            )
        return self


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def calculate_event_idempotency_key(
    *,
    source: str,
    event_type: str,
    external_project_id: str | None,
    external_work_package_id: str | None,
    external_comment_id: str | None,
    payload: dict[str, Any],
) -> str:
    fingerprint_input = {
        "source": source,
        "event_type": event_type,
        "external_project_id": external_project_id,
        "external_work_package_id": external_work_package_id,
        "external_comment_id": external_comment_id,
        "payload": payload,
    }
    digest = hashlib.sha256(canonical_json(fingerprint_input).encode("utf-8")).hexdigest()
    return f"{source}:{digest}"
