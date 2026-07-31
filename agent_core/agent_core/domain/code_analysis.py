from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CodeSymbolKind(StrEnum):
    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    IMPORT = "import"


class CodeRelationshipKind(StrEnum):
    DEFINES = "defines"
    IMPORTS = "imports"
    CALLS = "calls"
    UNRESOLVED_CALL = "unresolved_call"


class CodeSymbol(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol_key: str
    repository_key: str
    relative_path: str
    name: str
    kind: CodeSymbolKind
    language: str
    start_line: int | None = None
    end_line: int | None = None
    parent_symbol_key: str | None = None
    metadata: dict = Field(default_factory=dict)


class CodeRelationship(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository_key: str
    source_symbol_key: str
    relationship_type: CodeRelationshipKind
    target_symbol_key: str | None = None
    target_name: str | None = None
    metadata: dict = Field(default_factory=dict)


class RepositoryIndex(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository_key: str
    symbols: tuple[CodeSymbol, ...] = Field(default_factory=tuple)
    relationships: tuple[CodeRelationship, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)


class SyntaxExtractionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    source: str
    relative_path: str
    functions: tuple[dict, ...] = Field(default_factory=tuple)
    classes: tuple[dict, ...] = Field(default_factory=tuple)
    calls: tuple[dict, ...] = Field(default_factory=tuple)
    imports: tuple[dict, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)


class LspLocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    uri: str
    line: int
    character: int


class LspLookupResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    locations: tuple[LspLocation, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
