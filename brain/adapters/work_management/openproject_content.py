"""OpenProject attachment content fetcher (Phase 1.4).

Downloads the raw bytes of an attachment behind its ``downloadLocation`` URL
using the same API-key authentication as the REST transport.  Only the adapter
package sees the provider's URL scheme; the ingestion service depends on the
:class:`AttachmentContentFetcher` port.
"""

from __future__ import annotations

import base64
import urllib.request

from brain.ports.attachment_content import AttachmentContentFetcher


class OpenProjectAttachmentContentFetcher(AttachmentContentFetcher):
    """AttachmentContentFetcher for OpenProject download URLs."""

    def __init__(self, base_url: str, api_key: str, timeout_seconds: int = 30) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds

    @property
    def _auth_header(self) -> str:
        credentials = f"apikey:{self._api_key}"
        return "Basic " + base64.b64encode(credentials.encode("utf-8")).decode("ascii")

    async def fetch(self, url: str) -> bytes:
        request = urllib.request.Request(
            url,
            headers={"Authorization": self._auth_header},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                return bytes(response.read())
        except Exception as exc:  # noqa: BLE001
            raise OpenProjectAttachmentError(f"attachment fetch failed: {exc}") from exc


class OpenProjectAttachmentError(RuntimeError):
    """Raised when an OpenProject attachment download fails."""


__all__ = ["OpenProjectAttachmentContentFetcher", "OpenProjectAttachmentError"]
