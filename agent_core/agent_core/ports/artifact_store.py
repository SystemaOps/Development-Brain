from __future__ import annotations

from typing import Protocol


class ArtifactStorePort(Protocol):
    async def write_text(self, *, key: str, content: str, content_type: str = "text/plain") -> str:
        ...

    async def read_text(self, *, uri: str) -> str:
        ...
