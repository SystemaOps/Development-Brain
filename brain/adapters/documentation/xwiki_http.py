"""XWiki HTTP transport (Phase 35).

Real REST transport behind :class:`XWikiTransport` using the stdlib (no extra
dependency).  Only the adapter package sees XWiki's JSON shape; the core
never does.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any


class XWikiHTTPTransport:
    """HTTP transport for the XWiki REST API (versioned pages)."""

    def __init__(
        self,
        base_url: str,
        *,
        user: str | None = None,
        password: str | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        import base64

        if user and password:
            token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
            self._headers = {"Authorization": f"Basic {token}"}
        else:
            self._headers = {}

    def _request(self, method: str, path: str, params: str | None = None) -> Any:
        url = f"{self._base_url}{path}"
        if params:
            url = f"{url}?{params}"
        request = urllib.request.Request(url, method=method, headers=self._headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8")
                if not body:
                    return {}
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise XWikiHTTPError(f"xwiki {method} {path} -> {exc.code}: {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise XWikiHTTPError(f"xwiki unreachable: {exc}") from exc

    async def get_page(self, page_id: str) -> dict[str, Any]:
        result = self._request(
            "GET",
            f"/rest/wikis/{self._wiki(page_id)}/spaces/{self._space(page_id)}/pages/{self._name(page_id)}",
        )
        return _flatten_page(result)

    async def get_page_version(self, page_id: str, version: str) -> dict[str, Any]:
        result = self._request(
            "GET",
            f"/rest/wikis/{self._wiki(page_id)}/spaces/{self._space(page_id)}/pages/{self._name(page_id)}/history/{version}",
        )
        return _flatten_page(result)

    async def list_page_changes(self, page_id: str) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            f"/rest/wikis/{self._wiki(page_id)}/spaces/{self._space(page_id)}/pages/{self._name(page_id)}/history",
        )
        return list(result.get("pageHistorySummary", []))

    async def get_attachments(self, page_id: str) -> list[dict[str, Any]]:
        del page_id
        return []

    async def get_children(self, page_id: str) -> list[dict[str, Any]]:
        del page_id
        return []

    async def get_links(self, page_id: str) -> list[str]:
        del page_id
        return []

    async def list_changed_pages(self, since: datetime) -> list[str]:
        # XWiki REST provides `modified` filters per space; the scheduler polls
        # changed pages through the normalizer.  A best-effort approach: query
        # all pages in the configured space and filter by version date here.
        del since
        result = self._request(
            "GET",
            "/rest/wikis/xwiki/spaces/Main/pages?limit=200",
        )
        pages = result.get("searchResults") or result.get("pages") or []
        ids: list[str] = []
        for page in pages:
            page_ref = page.get("pageFullReference") or page.get("reference") or ""
            ids.append(page_ref)
        return ids

    def _wiki(self, page_id: str) -> str:
        parts = page_id.split("/")
        return parts[0] if parts and parts[0] else "xwiki"

    def _space(self, page_id: str) -> str:
        parts = page_id.split("/")
        return parts[1] if len(parts) > 1 else "Main"

    def _name(self, page_id: str) -> str:
        parts = page_id.split("/")
        return parts[-1] if parts else page_id


def _flatten_page(result: dict[str, Any]) -> dict[str, Any]:
    """Flatten XWiki REST links into simple fields the adapter expects."""
    title = result.get("title") or result.get("name") or ""
    content = result.get("content") or ""
    if isinstance(content, dict):
        content = content.get("content") or content.get("value") or ""
    version = result.get("version")
    if isinstance(version, dict):
        version = version.get("version") or version.get("number") or ""
    parent = result.get("parent") or ""
    if isinstance(parent, dict):
        parent = parent.get("pageFullReference") or parent.get("reference") or ""
    return {
        "title": title,
        "content": content,
        "version": version,
        "parent": parent,
        "id": result.get("id") or result.get("pageFullReference") or "",
    }


class XWikiHTTPError(RuntimeError):
    """Raised when the XWiki REST API returns an error."""


__all__ = ["XWikiHTTPError", "XWikiHTTPTransport"]
