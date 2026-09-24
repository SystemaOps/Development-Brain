"""XWiki HTTP transport (Phase 35).

Real REST transport behind :class:`XWikiTransport` using the stdlib (no extra
dependency).  Only the adapter package sees XWiki's JSON shape; the core
never does.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

XWIKI_SOLR_PAGE_SIZE = 50


class XWikiHTTPTransport:
    """HTTP transport for the XWiki REST API (versioned pages)."""

    def __init__(
        self,
        base_url: str,
        *,
        user: str | None = None,
        password: str | None = None,
        wiki: str = "xwiki",
        timeout_seconds: int = 30,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._wiki_name = wiki
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
        request = urllib.request.Request(
            url,
            method=method,
            headers={**self._headers, "Accept": "application/json"},
        )
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

    def _space_url_path(self, space: str) -> str:
        """REST path segments for a (possibly nested) space.

        XWiki's REST API addresses nested spaces with repeated ``/spaces/{child}``
        segments (``odoogarageeu.Architecture`` -> ``/spaces/odoogarageeu/spaces/Architecture``);
        the dotted form returns 404.
        """
        parts = [p for p in space.split(".") if p]
        return "/".join(f"spaces/{urllib.parse.quote(p, safe='')}" for p in parts)

    async def get_page(self, page_id: str) -> dict[str, Any]:
        result = self._request(
            "GET",
            f"/rest/wikis/{self._wiki(page_id)}/{self._space_url_path(self._space(page_id))}/pages/{self._name(page_id)}",
        )
        return _flatten_page(result)

    async def create_space(self, space: str) -> dict[str, Any]:
        """Create a wiki space by creating its ``WebHome`` page.

        The XWiki REST API does not accept PUT on the spaces collection; a
        page PUT into a non-existent space creates the space implicitly.
        Requires authenticated access.  A freshly created space can transiently
        fail to read back, so the request is retried once.
        """
        import time

        payload = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<page xmlns="http://www.xwiki.org">'
            f"<title>{space}</title><content>Welcome to {space}</content>"
            "</page>"
        )
        url = (
            f"{self._base_url}/rest/wikis/{self._wiki_name}"
            f"/spaces/{urllib.parse.quote(space, safe='')}/pages/WebHome"
        )
        last_error: Exception | None = None
        for attempt in range(2):
            request = urllib.request.Request(
                url,
                data=payload.encode("utf-8"),
                headers={"Content-Type": "application/xml", **self._headers},
                method="PUT",
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                    raw = response.read().decode("utf-8")
                    if not raw:
                        return {}
                    return dict(json.loads(raw)) if raw.lstrip().startswith("{") else {}
            except urllib.error.HTTPError as exc:
                last_error = XWikiHTTPError(
                    f"xwiki PUT space {space} -> {exc.code}: "
                    f"{exc.read().decode('utf-8', errors='replace')}"
                )
                if exc.code < 500:
                    raise last_error from exc
            except (urllib.error.URLError, OSError) as exc:
                last_error = XWikiHTTPError(f"xwiki unreachable: {exc}")
            if attempt == 0:
                time.sleep(2)
        assert last_error is not None
        raise last_error

    async def get_page_version(self, page_id: str, version: str) -> dict[str, Any]:
        result = self._request(
            "GET",
            f"/rest/wikis/{self._wiki(page_id)}/{self._space_url_path(self._space(page_id))}/pages/{self._name(page_id)}/history/{version}",
        )
        return _flatten_page(result)

    async def list_page_changes(self, page_id: str) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            f"/rest/wikis/{self._wiki(page_id)}/{self._space_url_path(self._space(page_id))}/pages/{self._name(page_id)}/history",
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

    async def list_changed_pages(
        self,
        spaces: list[str],
        since: datetime | None = None,
        *,
        page_size: int = XWIKI_SOLR_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """List pages in the given spaces (including nested spaces) modified after ``since``.

        Uses the Solr query endpoint ordered by modification date descending.
        Each mapped space is queried twice — ``space:X`` for its direct pages
        and ``space:X.*`` for pages in nested spaces (e.g.
        ``odoogarageeu.Architecture.WebHome``).  Because results arrive
        newest-first, pagination stops as soon as a page older than ``since``
        is seen (no full-space scans).  Returns normalized page metadata
        sorted by (space, page reference).
        """
        import urllib.parse

        results: list[dict[str, Any]] = []
        for space in spaces:
            for query_space in (space, f"{space}.*"):
                start = 0
                while True:
                    params = urllib.parse.urlencode(
                        {
                            "q": f"space:{query_space}",
                            "type": "solr",
                            "start": start,
                            "number": page_size,
                            "orderField": "date",
                            "order": "desc",
                        }
                    )
                    payload = self._request(
                        "GET", f"/rest/wikis/{self._wiki_name}/query", params=params
                    )
                    elements = list(payload.get("searchResults") or [])
                    if not elements:
                        break
                    stop = False
                    for element in elements:
                        normalized = _normalize_query_page(element)
                        modified_dt = _parse_modified(normalized["modified"])
                        if since is not None and modified_dt is not None and modified_dt < since:
                            stop = True
                            break
                        results.append(normalized)
                    if stop or len(elements) < page_size:
                        break
                    start += page_size
        # A page lives in exactly one space, so direct and nested queries never
        # overlap; dedupe defensively (mirrors Solr's tokenized matching).
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for page in sorted(results, key=lambda p: (str(p["space"]), str(p["id"]))):
            if page["id"] in seen:
                continue
            seen.add(page["id"])
            deduped.append(page)
        return deduped

    def _wiki(self, page_id: str) -> str:
        # The wiki name is configured, never derived from a page reference.
        del page_id
        return self._wiki_name

    def _space(self, page_id: str) -> str:
        """Extract the space path from a page reference.

        References arrive dotted (``Main.WebHome``, ``odoogarage.Requirements.WebHome``)
        or slash-form (``xwiki/Main/WebHome``).  In both forms the last segment is
        the page name and everything before it is the (possibly nested) space.
        """
        if "/" in page_id:
            segments = [s for s in page_id.split("/") if s]
            rest = segments[1:] if segments and segments[0] == self._wiki_name else segments
            if not rest:
                return "Main"
            return ".".join(rest[:-1]) if len(rest) > 1 else rest[0]
        if "." in page_id:
            return page_id.rsplit(".", 1)[0] or "Main"
        return "Main"

    def _name(self, page_id: str) -> str:
        if "/" in page_id:
            return page_id.rstrip("/").rsplit("/", 1)[-1]
        if "." in page_id:
            return page_id.rsplit(".", 1)[-1]
        return page_id


def _to_iso(modified: object) -> str:
    """Normalize an XWiki ``modified`` value (epoch millis) to ISO text."""
    if isinstance(modified, (int, float)):
        from datetime import UTC, datetime

        return datetime.fromtimestamp(modified / 1000, tz=UTC).isoformat()
    if isinstance(modified, dict):
        return str(modified.get("value") or "")
    return str(modified) if modified else ""


def _parse_modified(value: object) -> datetime | None:
    """Parse a normalized modified value back into an aware UTC datetime."""
    from datetime import UTC, datetime

    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _normalize_query_page(element: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Solr query search result into page metadata.

    XWiki's Solr JSON escapes special characters (notably ``.``) in
    ``pageFullName`` and ``space`` (e.g. ``hierarchy-test\\.Child.WebHome``);
    unescape them so the reference round-trips into REST URLs.
    """
    return {
        "id": _unescape_solr(str(element.get("pageFullName") or element.get("id") or "")),
        "space": _unescape_solr(str(element.get("space") or "")),
        "title": str(element.get("title") or ""),
        "version": str(element.get("version") or ""),
        "modified": _to_iso(element.get("modified")),
    }


def _unescape_solr(value: str) -> str:
    return value.replace("\\.", ".")


def _flatten_page(result: dict[str, Any]) -> dict[str, Any]:
    """Flatten XWiki REST JSON page fields into the shape the adapter expects.

    ``modified`` arrives as epoch milliseconds; ``version``/``syntax`` are
    plain strings in the JSON representation.
    """
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
    syntax = result.get("syntax") or ""
    if isinstance(syntax, dict):
        syntax = syntax.get("id") or syntax.get("value") or ""
    modified = result.get("modified")
    if isinstance(modified, dict):
        modified = modified.get("value") or ""
    if isinstance(modified, (int, float)):
        from datetime import UTC, datetime

        modified = datetime.fromtimestamp(modified / 1000, tz=UTC).isoformat()
    return {
        "title": title,
        "content": content,
        "version": str(version),
        "parent": str(parent),
        "id": result.get("fullName") or result.get("id") or result.get("pageFullReference") or "",
        "syntax": str(syntax),
        "modified": str(modified) if modified else "",
        "space": result.get("space") or "",
    }


class XWikiHTTPError(RuntimeError):
    """Raised when the XWiki REST API returns an error."""


__all__ = ["XWikiHTTPError", "XWikiHTTPTransport", "XWIKI_SOLR_PAGE_SIZE"]
