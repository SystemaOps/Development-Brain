"""OpenProject HTTP transport (Phase 34).

Real REST transport behind :class:`OpenProjectTransport` using the stdlib
(no extra dependency).  Only the adapter package sees OpenProject's JSON
shape; the core never does.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any


class OpenProjectHTTPTransport:
    """HTTP transport for the OpenProject REST API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_seconds: int = 30,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds

    @property
    def _auth_header(self) -> str:
        # OpenProject 16 authenticates API keys through Warden basic auth with
        # the literal user name "apikey" and the API key as the password
        # (``Authorization: Basic base64(apikey:<key>)``).  The legacy
        # ``Authorization: apikey <key>`` header is not accepted.
        credentials = f"apikey:{self._api_key}"
        return "Basic " + base64.b64encode(credentials.encode("utf-8")).decode("ascii")

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {"Authorization": self._auth_header}
        data: bytes | None = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8")
                if not body:
                    return {}
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    return parsed
                return {"_items": parsed}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OpenProjectHTTPError(
                f"openproject {method} {path} -> {exc.code}: {body}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise OpenProjectHTTPError(f"openproject unreachable: {exc}") from exc

    async def get_work_package(self, external_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v3/work_packages/{external_id}")

    def _updated_since_filters(self, since: datetime, project_id: str | None = None) -> str:
        """OpenProject ``updatedAt`` filter values.

        The filter only accepts the ``<>d`` between-dates operator with date
        (not datetime) values; a far-future upper bound makes it "updated
        since".  Date granularity is fine because re-pulling items from the
        same day is idempotent (snapshot diff).  When ``project_id`` is given,
        the query is scoped to that provider project.
        """
        import json
        import urllib.parse

        start = since.strftime("%Y-%m-%d")
        filters = [{"updatedAt": {"operator": "<>d", "values": [start, "2099-12-31"]}}]
        if project_id:
            filters.insert(0, {"project": {"operator": "=", "values": [project_id]}})
        return urllib.parse.quote(json.dumps(filters), safe="")

    async def list_updated_work_packages(self, since: datetime) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            f"/api/v3/work_packages?filters={self._updated_since_filters(since)}",
        )
        return list(result.get("_embedded", {}).get("elements", []))

    async def list_updated_work_packages_page(
        self,
        since: datetime,
        *,
        offset: int = 1,
        page_size: int = 100,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            f"/api/v3/work_packages?filters={self._updated_since_filters(since, project_id)}"
            f"&offset={offset}&pageSize={page_size}",
        )
        return list(result.get("_embedded", {}).get("elements", []))

    async def list_projects(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/api/v3/projects")
        return list(result.get("_embedded", {}).get("elements", []))

    async def list_project_work_packages(
        self,
        project_external_id: str,
        *,
        offset: int = 1,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            f"/api/v3/projects/{project_external_id}/work_packages"
            f"?offset={offset}&pageSize={page_size}",
        )
        return list(result.get("_embedded", {}).get("elements", []))

    async def get_activities(self, external_id: str) -> list[dict[str, Any]]:
        result = self._request("GET", f"/api/v3/work_packages/{external_id}/activities")
        return list(result.get("_embedded", {}).get("elements", []))

    async def create_work_package(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v3/work_packages", payload)

    async def create_project(self, name: str, description: str | None = None) -> dict[str, Any]:
        identifier = _project_identifier(name)
        payload: dict[str, Any] = {
            "name": name,
            "identifier": identifier,
            "description": {"raw": description or ""},
        }
        return self._request("POST", "/api/v3/projects", payload)

    async def update_status(self, external_id: str, status: str) -> None:
        self._request(
            "PATCH",
            f"/api/v3/work_packages/{external_id}",
            {"_links": {"status": {"href": f"/api/v3/statuses/{status}"}}},
        )

    async def post_comment(self, external_id: str, body: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v3/work_packages/{external_id}/activities",
            {"comment": {"raw": body}},
        )

    async def link_pull_request(self, external_id: str, pr_ref: str) -> None:
        del pr_ref
        # PR linking is provider-specific; keep it a no-op for Milestone 2.
        return None


def _project_identifier(name: str) -> str:
    """Slugify a project name into an OpenProject identifier ([a-z0-9_])."""
    lowered = name.strip().lower()
    chars = []
    for ch in lowered:
        if ch.isalnum():
            chars.append(ch)
        elif chars and chars[-1] != "_":
            chars.append("_")
    identifier = "".join(chars).strip("_")
    return identifier or "project"


class OpenProjectHTTPError(RuntimeError):
    """Raised when the OpenProject REST API returns an error."""


__all__ = ["OpenProjectHTTPError", "OpenProjectHTTPTransport", "_project_identifier"]
