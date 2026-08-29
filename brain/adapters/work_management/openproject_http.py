"""OpenProject HTTP transport (Phase 34).

Real REST transport behind :class:`OpenProjectTransport` using the stdlib
(no extra dependency).  Only the adapter package sees OpenProject's JSON
shape; the core never does.
"""

from __future__ import annotations

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

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"apikey {self._api_key}"}
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

    async def list_updated_work_packages(self, since: datetime) -> list[dict[str, Any]]:
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = self._request(
            "GET",
            f'/api/v3/work_packages?filters=[{{"updatedAt":{{"operator":">d","values":["{since_iso}"]}}}}]',
        )
        return list(result.get("_embedded", {}).get("elements", []))

    async def create_work_package(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v3/work_packages", payload)

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


class OpenProjectHTTPError(RuntimeError):
    """Raised when the OpenProject REST API returns an error."""


__all__ = ["OpenProjectHTTPError", "OpenProjectHTTPTransport"]
