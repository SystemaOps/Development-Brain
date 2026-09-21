"""GitLab project provisioning adapter (Phase 2.2).

Creates GitLab projects via ``POST /api/v4/projects`` using the same
``PRIVATE-TOKEN`` auth as the merge-request adapter.  Only this adapter sees
GitLab's JSON shape; the provisioning service depends on the
:class:`SourceControlProvisioningPort`.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from brain.domain.external_reference import ExternalReference
from brain.ports.provisioning import SourceControlProvisioningPort


class GitLabProjectProvisioningAdapter(SourceControlProvisioningPort):
    """SourceControlProvisioningPort backed by the GitLab REST API."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        timeout_seconds: int = 30,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["PRIVATE-TOKEN"] = api_key

    async def create_project(self, name: str, description: str | None = None) -> ExternalReference:
        body = {
            "name": name,
            "path": _project_path(name),
            "description": description or "",
            "visibility": "private",
        }
        result = self._request("POST", "/api/v4/projects", data=body)
        return ExternalReference(
            provider="gitlab",
            external_id=str(result.get("id", "")),
            external_type="project",
            namespace=str(result.get("path_with_namespace") or result.get("path") or ""),
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
                raw = response.read().decode("utf-8")
                if not raw:
                    return {}
                return dict(json.loads(raw))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitLabProvisioningError(
                f"gitlab {method} {path} -> {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise GitLabProvisioningError(f"gitlab unreachable: {exc}") from exc


def _project_path(name: str) -> str:
    """Slugify a project name into a GitLab path (lowercase, dashes)."""
    lowered = name.strip().lower()
    chars = []
    for ch in lowered:
        if ch.isalnum():
            chars.append(ch)
        elif chars and chars[-1] != "-":
            chars.append("-")
    path = "".join(chars).strip("-")
    return path or "project"


class GitLabProvisioningError(RuntimeError):
    """Raised when a GitLab project-creation request fails."""


__all__ = ["GitLabProjectProvisioningAdapter", "GitLabProvisioningError", "_project_path"]
