from __future__ import annotations

import asyncio
import importlib
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_core.domain.code_analysis import LspLocation, LspLookupResult
from agent_core.domain.repositories import (
    RepositoryBinding,
    resolve_repository_path,
    resolve_repository_root,
)
from agent_core.ports.repository_analysis import LspLookupPort


class LegacyPythonLspLookup(LspLookupPort):
    def __init__(
        self,
        *,
        binding: RepositoryBinding,
        client_factory: Callable[[str], Any] | None = None,
        enabled: bool = True,
    ):
        self.binding = binding
        self.client_factory = client_factory
        self.enabled = enabled

    def is_available(self) -> bool:
        if not self.enabled:
            return False
        if self.client_factory is not None:
            return True
        if shutil.which("pyright-langserver") is None:
            return False
        try:
            importlib.import_module("src.parser.lsp_client")
        except ImportError:
            return False
        return True

    async def definition(
        self,
        *,
        repository_key: str,
        relative_path: str,
        line: int,
        character: int,
    ) -> LspLookupResult:
        return await asyncio.to_thread(
            self._lookup,
            "definition",
            repository_key,
            relative_path,
            line,
            character,
        )

    async def references(
        self,
        *,
        repository_key: str,
        relative_path: str,
        line: int,
        character: int,
    ) -> LspLookupResult:
        return await asyncio.to_thread(
            self._lookup,
            "references",
            repository_key,
            relative_path,
            line,
            character,
        )

    def _lookup(
        self,
        method_name: str,
        repository_key: str,
        relative_path: str,
        line: int,
        character: int,
    ) -> LspLookupResult:
        if repository_key != self.binding.repository_key:
            return LspLookupResult(
                available=False,
                warnings=(f"Unknown repository for LSP lookup: {repository_key}",),
            )
        if not self.is_available():
            return LspLookupResult(
                available=False,
                warnings=(
                    "LSP lookup is unavailable; install pyright-langserver and include the "
                    "legacy LSP client to enable definition/reference lookup.",
                ),
            )

        resolved_path = resolve_repository_path(self.binding, relative_path)
        root = resolve_repository_root(self.binding)
        client = self._create_client(root)
        try:
            client.initialize()
            client.did_open(str(resolved_path.absolute_path))
            raw_result = getattr(client, method_name)(
                str(resolved_path.absolute_path),
                line,
                character,
            )
            return LspLookupResult(
                available=True,
                locations=tuple(_normalize_lsp_locations(raw_result)),
            )
        except Exception as exc:
            return LspLookupResult(
                available=False,
                warnings=(
                    f"LSP {method_name} lookup failed: {type(exc).__name__}: {exc}",
                ),
            )
        finally:
            try:
                client.shutdown()
            except Exception:
                pass

    def _create_client(self, root: Path) -> Any:
        if self.client_factory is not None:
            return self.client_factory(str(root))
        module = importlib.import_module("src.parser.lsp_client")
        return module.LspClient(str(root))


def _normalize_lsp_locations(location: Any) -> list[LspLocation]:
    if not location:
        return []

    items = location if isinstance(location, list) else [location]
    normalized: list[LspLocation] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "targetUri" in item and "targetSelectionRange" in item:
            start = item["targetSelectionRange"]["start"]
            normalized.append(
                LspLocation(
                    uri=item["targetUri"],
                    line=int(start["line"]),
                    character=int(start["character"]),
                )
            )
        elif "uri" in item and "range" in item:
            start = item["range"]["start"]
            normalized.append(
                LspLocation(
                    uri=item["uri"],
                    line=int(start["line"]),
                    character=int(start["character"]),
                )
            )
    return normalized
