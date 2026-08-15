"""Actors: humans, agents, automation, and systems share one abstraction.

A task can be assigned to a human developer or to a coding agent; both are
``Actor`` instances so routing and execution history stay uniform.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import ActorId, new_actor_id


class ActorType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    AUTOMATION = "automation"
    SYSTEM = "system"
    CI = "ci"


class Actor(BaseModel):
    id: ActorId = Field(default_factory=new_actor_id)
    actor_type: ActorType
    display_name: str
    capabilities: list[str] = Field(default_factory=list)
