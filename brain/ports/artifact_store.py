"""Artifact/object store port.

Holds original PDFs, DOCX files, large logs, test reports, patch bundles, and
other blob-like artifacts (S3, MinIO, local filesystem, ...).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ArtifactStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str | None = None) -> str: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...
