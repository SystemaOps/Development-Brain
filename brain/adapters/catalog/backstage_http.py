"""Backstage HTTP transport (Phase 36).

Real REST transport behind :class:`BackstageTransport` using the stdlib (no
extra dependency).  Only the adapter package sees Backstage's JSON shape.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class BackstageHTTPTransport:
    """HTTP transport for the Backstage catalog API."""

    def __init__(self, base_url: str, *, timeout_seconds: int = 30) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def _get(self, path: str) -> Any:
        request = urllib.request.Request(f"{self._base_url}{path}", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8")
                if not body:
                    return {"items": []}
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BackstageHTTPError(f"backstage {path} -> {exc.code}: {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise BackstageHTTPError(f"backstage unreachable: {exc}") from exc

    async def list_entities(self, kind: str) -> list[dict[str, Any]]:
        result = self._get(f"/api/catalog/entities?filter=kind={kind}")
        items = result.get("items") if isinstance(result, dict) else result
        return list(items or [])

    async def list_dependencies(self) -> list[tuple[str, str]]:
        # Backstage does not expose a global dependency endpoint; dependencies
        # are inferred per-component by the derived catalog.  Return nothing.
        return []


class BackstageHTTPError(RuntimeError):
    """Raised when the Backstage catalog API returns an error."""


__all__ = ["BackstageHTTPError", "BackstageHTTPTransport"]
