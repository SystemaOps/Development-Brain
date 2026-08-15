"""Architecture boundary tests.

Enforce the ports-and-adapters rules of the brain:

- ``brain.domain`` must not import adapters or any provider SDK.
- ``brain.ports`` must not import adapters or provider SDKs.
- ``brain.adapters`` may import domain and ports but not provider SDKs.

These tests are AST-based and run without external infrastructure.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
from collections.abc import Iterator

import brain.adapters
import brain.domain
import brain.ports

# Top-level modules that leak provider/implementation concerns into the core.
PROVIDER_MODULES = {
    "sqlalchemy",
    "sqlmodel",
    "asyncpg",
    "psycopg",
    "neo4j",
    "weaviate",
    "redis",
    "langgraph",
    "langchain",
    "openproject",
    "jira",
    "atlassian",
    "docling",
    "fastapi",
    "starlette",
    "aiohttp",
    "httpx",
    "requests",
}


def _iter_modules(package: object) -> Iterator[object]:
    for module_info in pkgutil.walk_packages(package.__path__, prefix=package.__name__ + "."):
        yield importlib.import_module(module_info.name)


def _module_source(module: object) -> str:
    path = getattr(module, "__file__", None)
    if path is None:
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _imported_top_levels(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module != "__future__"
        ):
            names.add(node.module.split(".")[0])
    return names


def test_domain_never_imports_adapters() -> None:
    for module in _iter_modules(brain.domain):
        top = _imported_top_levels(_module_source(module))
        assert "adapters" not in top, f"{module.__name__} imports adapters"
        assert not (top & PROVIDER_MODULES), (
            f"{module.__name__} imports provider modules {top & PROVIDER_MODULES}"
        )


def test_ports_never_import_adapters_or_providers() -> None:
    for module in _iter_modules(brain.ports):
        top = _imported_top_levels(_module_source(module))
        assert "adapters" not in top, f"{module.__name__} imports adapters"
        assert not (top & PROVIDER_MODULES), (
            f"{module.__name__} imports provider modules {top & PROVIDER_MODULES}"
        )


def test_adapters_never_import_provider_sdks() -> None:
    for module in _iter_modules(brain.adapters):
        top = _imported_top_levels(_module_source(module))
        assert not (top & PROVIDER_MODULES), (
            f"{module.__name__} imports provider modules {top & PROVIDER_MODULES}"
        )


def test_domain_has_no_external_dependencies_beyond_pydantic() -> None:
    for module in _iter_modules(brain.domain):
        top = _imported_top_levels(_module_source(module))
        external = top - {"brain", "pydantic", "uuid", "typing", "enum", "datetime", "re"}
        assert not external, f"{module.__name__} imports unexpected modules {external}"
