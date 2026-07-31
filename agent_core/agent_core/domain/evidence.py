from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvidenceRef(BaseModel):
    evidence_type: str
    uri: str
    title: str | None = None
    excerpt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
