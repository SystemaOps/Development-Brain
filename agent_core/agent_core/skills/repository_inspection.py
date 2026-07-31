from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_core.domain.code_analysis import CodeRelationship, CodeSymbol
from agent_core.domain.evidence import EvidenceRef
from agent_core.skills.base import BaseSkill, SkillContext, SkillResult


class RepositoryInspectionInput(BaseModel):
    repository_key: str | None = None
    symbols: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    max_symbols: int = Field(default=200, ge=1, le=2000)


class RepositoryInspectionSummary(BaseModel):
    repository_key: str | None = None
    symbol_count: int = 0
    relationship_count: int = 0
    file_count: int = 0
    function_count: int = 0
    class_count: int = 0
    test_symbol_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class RepositoryEvidence(BaseModel):
    evidence_type: str
    repository_key: str | None = None
    relative_path: str | None = None
    symbol_key: str | None = None
    name: str
    kind: str
    uri: str
    excerpt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RepositoryInspectionOutput(BaseModel):
    summary: RepositoryInspectionSummary
    files: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    classes: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    evidence: list[RepositoryEvidence] = Field(default_factory=list)
    source_refs: list[EvidenceRef] = Field(default_factory=list)


class RepositoryInspectionSkill(BaseSkill):
    name = "repository_inspection"
    description = "Summarizes repository symbols and implementation evidence."
    input_schema = RepositoryInspectionInput
    output_schema = RepositoryInspectionOutput
    side_effects = False

    def __init__(self, db: Any | None = None):
        self.db = db

    def can_handle(self, intent: str, context: SkillContext) -> float:
        lowered = intent.lower()
        if any(word in lowered for word in ["repository", "repo", "code", "implementation", "symbols"]):
            return 0.9
        return 0.3

    async def run(
        self,
        *,
        intent: str,
        context: SkillContext,
        input_data: dict[str, Any],
    ) -> SkillResult:
        parsed = RepositoryInspectionInput.model_validate(input_data or {})
        repository_key = parsed.repository_key or context.metadata.get("repository_key")
        symbols = list(parsed.symbols)
        relationships = list(parsed.relationships)
        warnings: list[str] = []

        if not symbols and repository_key and self.db is not None:
            try:
                from agent_core.services.repository_analysis_service import RepositoryAnalysisService

                service = RepositoryAnalysisService(self.db)
                loaded_symbols = await service.list_symbols(
                    project_key=context.project_key,
                    repository_key=repository_key,
                )
                loaded_relationships = await service.list_relationships(
                    project_key=context.project_key,
                    repository_key=repository_key,
                )
                symbols = [symbol.model_dump(mode="json") for symbol in loaded_symbols]
                relationships = [relation.model_dump(mode="json") for relation in loaded_relationships]
            except Exception as exc:  # pragma: no cover - exact DB failure depends on deployment
                warnings.append(f"Repository index lookup failed: {exc}")

        if not symbols:
            warnings.append("No repository symbols were provided or found for inspection.")

        normalized_symbols = [_normalize_symbol(item) for item in symbols[: parsed.max_symbols]]
        files = sorted(_display_symbol(symbol) for symbol in normalized_symbols if symbol.get("kind") == "file")
        functions = sorted(_display_symbol(symbol) for symbol in normalized_symbols if symbol.get("kind") == "function")
        classes = sorted(_display_symbol(symbol) for symbol in normalized_symbols if symbol.get("kind") == "class")
        tests = sorted(
            _display_symbol(symbol)
            for symbol in normalized_symbols
            if _is_test_symbol(symbol)
        )
        evidence = [_evidence_from_symbol(symbol, repository_key) for symbol in normalized_symbols]
        source_refs = [
            EvidenceRef(
                evidence_type="code_symbol",
                uri=item.uri,
                title=item.name,
                excerpt=item.excerpt,
                metadata=item.metadata,
            )
            for item in evidence
        ]

        output = RepositoryInspectionOutput(
            summary=RepositoryInspectionSummary(
                repository_key=repository_key,
                symbol_count=len(symbols),
                relationship_count=len(relationships),
                file_count=len(files),
                function_count=len(functions),
                class_count=len(classes),
                test_symbol_count=len(tests),
                warnings=warnings,
            ),
            files=files,
            functions=functions,
            classes=classes,
            tests=tests,
            evidence=evidence,
            source_refs=source_refs,
        )
        return SkillResult(
            skill_name=self.name,
            success=True,
            output=output.model_dump(mode="json"),
            source_refs=[ref.model_dump(mode="json") for ref in source_refs],
            errors=warnings,
        )


def _normalize_symbol(item: dict[str, Any] | CodeSymbol) -> dict[str, Any]:
    if isinstance(item, CodeSymbol):
        return item.model_dump(mode="json")
    return dict(item)


def _display_symbol(symbol: dict[str, Any]) -> str:
    path = symbol.get("relative_path") or "<unknown>"
    name = symbol.get("name") or path
    line = symbol.get("start_line")
    if line:
        return f"{name} ({path}:{line})"
    return f"{name} ({path})"


def _is_test_symbol(symbol: dict[str, Any]) -> bool:
    path = str(symbol.get("relative_path") or "").lower()
    name = str(symbol.get("name") or "").lower()
    return path.startswith("tests/") or "/test_" in path or path.endswith("_test.py") or name.startswith("test_")


def _evidence_from_symbol(symbol: dict[str, Any], fallback_repository_key: str | None) -> RepositoryEvidence:
    repository_key = symbol.get("repository_key") or fallback_repository_key
    relative_path = symbol.get("relative_path")
    symbol_key = symbol.get("symbol_key")
    name = str(symbol.get("name") or relative_path or symbol_key or "unknown")
    kind = str(symbol.get("kind") or "symbol")
    uri = f"repository://{repository_key or 'unknown'}/{relative_path or ''}"
    if symbol_key:
        uri = f"{uri}#{symbol_key}"
    excerpt = f"{kind} {name} in {relative_path or 'unknown path'}"
    return RepositoryEvidence(
        evidence_type="code_symbol",
        repository_key=repository_key,
        relative_path=relative_path,
        symbol_key=symbol_key,
        name=name,
        kind=kind,
        uri=uri,
        excerpt=excerpt,
        metadata={"line": symbol.get("start_line"), **(symbol.get("metadata") or {})},
    )
