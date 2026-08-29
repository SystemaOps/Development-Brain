"""Canonical code intelligence domain model (Phase 7).

Revision-aware source-code intelligence: parsing a file yields
:class:`ParsedFile` (symbols, imports, relations); symbols carry a stable
:class:`SymbolIdentity` derived from repository + revision + module + qualified
name + kind, never from a line number.  Relations are typed with the controlled
vocabulary (:class:`CodeRelationType`) and carry provenance/confidence, so a
later phase can project them into the knowledge graph without re-classifying.

The language parsers (Python AST first) live behind the ``LanguageParser``
port; the domain never depends on a provider.
"""

from __future__ import annotations

import hashlib
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import RepositoryId


class SymbolKind(StrEnum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    IMPORT = "import"
    VARIABLE = "variable"
    PARAMETER = "parameter"


class SymbolLocation(BaseModel):
    """Byte/line position of a symbol within a file."""

    path: str
    start_line: int = 0
    start_column: int = 0
    end_line: int = 0
    end_column: int = 0


class SymbolIdentity(BaseModel):
    """Stable identity for a symbol across revisions.

    Deliberately independent of line numbers: the same module/qualified
    name/kind at the same revision identifies the same symbol even when the
    file is edited above it.
    """

    repository_id: RepositoryId
    revision: str
    module: str
    qualified_name: str
    kind: SymbolKind

    @property
    def key(self) -> str:
        return ":".join(
            [
                str(self.repository_id),
                self.revision,
                self.module,
                self.qualified_name,
                self.kind.value,
            ]
        )


class Symbol(BaseModel):
    """A parsed symbol: module, class, function, method, import, ..."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    identity: SymbolIdentity
    name: str
    path: str
    kind: SymbolKind
    location: SymbolLocation
    qualified_name: str
    parameters: list[str] = Field(default_factory=list)
    return_annotation: str | None = None
    decorators: list[str] = Field(default_factory=list)
    docstring: str | None = None
    content_hash: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @property
    def identity_key(self) -> str:
        return self.identity.key


class CodeRelationType(StrEnum):
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    INSTANTIATES = "INSTANTIATES"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    OVERRIDES = "OVERRIDES"
    READS = "READS"
    WRITES = "WRITES"
    TESTS = "TESTS"


class CodeRelation(BaseModel):
    """A typed relation between two symbols in the same repository revision."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    relation_type: CodeRelationType
    source_identity: SymbolIdentity
    target_identity: SymbolIdentity
    repository_id: RepositoryId
    revision: str
    source_path: str
    target_path: str | None = None
    confidence: float = 1.0
    metadata: dict[str, object] = Field(default_factory=dict)


class ImportStatement(BaseModel):
    """A single import statement within a parsed file."""

    module: str
    name: str | None = None
    alias: str | None = None
    is_relative: bool = False
    level: int = 0
    is_local: bool | None = None
    location: SymbolLocation


class ParsedFile(BaseModel):
    """Canonical output of a language parser for one file at one revision."""

    path: str
    module: str
    language: str
    repository_id: RepositoryId
    revision: str
    content_hash: str
    symbols: list[Symbol] = Field(default_factory=list)
    imports: list[ImportStatement] = Field(default_factory=list)
    relations: list[CodeRelation] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)

    @property
    def symbol_identities(self) -> list[SymbolIdentity]:
        return [symbol.identity for symbol in self.symbols]


def module_from_path(path: str) -> str:
    """Derive a dotted module name from a file path.

    ``app/services/auth.py`` -> ``app.services.auth``
    ``__init__.py`` files contribute their directory only.
    """
    normalized = path.replace("\\", "/")
    if normalized.endswith(".py"):
        normalized = normalized[: -len(".py")]
    elif "." in normalized.rsplit("/", 1)[-1]:
        normalized = normalized.rsplit(".", 1)[0]
    parts = [part for part in normalized.split("/") if part and part != "__init__"]
    return ".".join(parts)


def content_hash(content: str) -> str:
    """Deterministic content hash for revision-aware knowledge."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def is_test_path(path: str) -> bool:
    """Heuristic for test files (test_*.py, *_test.py, tests/ dirs)."""
    normalized = path.replace("\\", "/")
    parts = [part.lower() for part in normalized.split("/")]
    if any(part in {"test", "tests", "spec", "specs", "__tests__"} for part in parts):
        return True
    name = normalized.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py")


__all__ = [
    "CodeRelation",
    "CodeRelationType",
    "ImportStatement",
    "ParsedFile",
    "Symbol",
    "SymbolIdentity",
    "SymbolKind",
    "SymbolLocation",
    "content_hash",
    "is_test_path",
    "module_from_path",
]
