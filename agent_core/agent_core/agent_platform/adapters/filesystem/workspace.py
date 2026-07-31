from __future__ import annotations

from pathlib import Path
from typing import Protocol


class FilesystemWorkspace(Protocol):
    """Platform-facing filesystem workspace abstraction for isolated agent workspaces."""

    def root(self) -> Path:
        ...

    def resolve(self, relative_path: str) -> Path:
        ...

    async def read_text(self, relative_path: str) -> str:
        ...

    async def write_text(self, relative_path: str, content: str) -> None:
        ...

    async def exists(self, relative_path: str) -> bool:
        ...


__all__ = ["FilesystemWorkspace"]
