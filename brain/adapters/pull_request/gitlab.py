"""GitLab merge request adapter (Task 38.2).

Implements :class:`PullRequestPort` against the GitLab REST API with the
stdlib (no extra dependency).  Only the adapter package sees GitLab's JSON
shape; the core never does.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import RepositoryId
from brain.domain.repositories import Repository
from brain.ports.pull_request import PullRequest, PullRequestPort


class GitLabPullRequestAdapter(PullRequestPort):
    """Creates/reads/updates merge requests via the GitLab REST API."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        project_id: str = "",
        timeout_seconds: int = 30,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._project_id = project_id
        self._timeout = timeout_seconds
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["PRIVATE-TOKEN"] = api_key

    async def create_pull_request(
        self,
        repository: Repository,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> ExternalReference:
        project = self._project_id or _project_from_repository(repository)
        body = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
        }
        result = self._request(
            "POST",
            f"/api/v4/projects/{_quote(project)}/merge_requests",
            data=body,
        )
        return ExternalReference(
            provider="gitlab",
            external_id=str(result.get("iid", "")),
            external_type="merge_request",
            namespace=project,
        )

    async def get_pull_request(self, ref: ExternalReference) -> PullRequest:
        project = ref.namespace or self._project_id
        result = self._request(
            "GET",
            f"/api/v4/projects/{_quote(project)}/merge_requests/{_quote(ref.external_id)}",
        )
        return _pr_from_response(result)

    async def update_pull_request(self, pull_request: PullRequest) -> None:
        project = self._project_id
        for ref in pull_request.external_refs:
            if ref.provider == "gitlab":
                project = ref.namespace or project
                break
        self._request(
            "PUT",
            f"/api/v4/projects/{_quote(project)}/merge_requests/{_quote(_iid_of(pull_request))}",
            data={
                "title": pull_request.title,
                "description": pull_request.description,
                "state_event": _state_event(pull_request.state),
            },
        )

    def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = json.dumps(data).encode("utf-8") if data is not None else None
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=payload,
            headers=self._headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8")
                if not body:
                    return {}
                return dict(json.loads(body))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitLabHTTPError(f"gitlab {method} {path} -> {exc.code}: {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise GitLabHTTPError(f"gitlab unreachable: {exc}") from exc


def _project_from_repository(repository: Repository) -> str:
    for ref in repository.external_refs:
        if ref.provider == "gitlab" and ref.external_type == "project":
            return ref.external_id
    # Fall back to the clone URL path: group/repo from both scp-style
    # (git@host:group/repo.git) and https-style (https://host/group/repo.git).
    url = repository.clone_url.replace("git@", "").replace("https://", "").replace("http://", "")
    if ":" in url.split("/", 1)[0]:
        return url.split(":", 1)[-1].rstrip("/").removesuffix(".git")
    return url.split("/", 1)[-1].rstrip("/").removesuffix(".git")


def _pr_from_response(result: dict[str, Any]) -> PullRequest:
    import uuid

    return PullRequest(
        repository_id=RepositoryId(uuid.UUID(int=0)),
        source_branch=str(result.get("source_branch") or ""),
        target_branch=str(result.get("target_branch") or ""),
        title=str(result.get("title") or ""),
        description=str(result.get("description") or ""),
        state=str(result.get("state") or "open"),
    )


def _iid_of(pull_request: PullRequest) -> str:
    for ref in pull_request.external_refs:
        if ref.provider == "gitlab":
            return ref.external_id
    return str(pull_request.id)


def _state_event(state: str) -> str:
    if state == "merged":
        return "merge"
    if state == "closed":
        return "close"
    return "reopen"


def _quote(value: str) -> str:
    import urllib.parse

    return urllib.parse.quote(value, safe="")


class GitLabHTTPError(RuntimeError):
    """Raised when the GitLab REST API returns an error."""


__all__ = ["GitLabHTTPError", "GitLabPullRequestAdapter"]
