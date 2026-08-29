"""Pull request port.

Canonical PR contracts live here; provider adapters (GitLab MR, GitHub PR, ...)
implement them behind the protocol.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import RepositoryId
from brain.domain.repositories import Repository


class PullRequest(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    repository_id: RepositoryId
    source_branch: str
    target_branch: str
    title: str
    description: str = ""
    state: str = "open"
    external_refs: list[ExternalReference] = Field(default_factory=list)


@runtime_checkable
class PullRequestPort(Protocol):
    async def create_pull_request(
        self,
        repository: Repository,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> ExternalReference: ...

    async def get_pull_request(self, ref: ExternalReference) -> PullRequest: ...

    async def update_pull_request(self, pull_request: PullRequest) -> None: ...
