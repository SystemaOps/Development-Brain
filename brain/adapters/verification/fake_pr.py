"""Fake pull-request adapter (Task 13.10).

Deterministic ``PullRequestPort`` implementation for tests: records PR creation
requests and returns a fake external reference.
"""

from __future__ import annotations

import uuid

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import RepositoryId
from brain.domain.repositories import Repository
from brain.ports.pull_request import PullRequest, PullRequestPort


class FakePullRequestAdapter(PullRequestPort):
    """Deterministic PR adapter for tests and offline runs."""

    def __init__(self) -> None:
        self.created: list[tuple[Repository, str, str, str, str]] = []
        self._refs: dict[str, PullRequest] = {}

    async def create_pull_request(
        self,
        repository: Repository,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> ExternalReference:
        self.created.append((repository, source_branch, target_branch, title, description))
        external_id = f"PR-{len(self.created)}"
        ref = ExternalReference(
            provider="fake",
            external_id=external_id,
            external_type="pull_request",
        )
        self._refs[external_id] = PullRequest(
            repository_id=repository.id,
            source_branch=source_branch,
            target_branch=target_branch,
            title=title,
            description=description,
        )
        return ref

    async def get_pull_request(self, ref: ExternalReference) -> PullRequest:
        pull_request = self._refs.get(ref.external_id)
        if pull_request is None:
            return PullRequest(
                repository_id=RepositoryId(uuid.UUID(int=0)),
                source_branch="",
                target_branch="",
                title="",
            )
        return pull_request

    async def update_pull_request(self, pull_request: PullRequest) -> None:
        self._refs[pull_request.id.__str__()] = pull_request


__all__ = ["FakePullRequestAdapter"]
