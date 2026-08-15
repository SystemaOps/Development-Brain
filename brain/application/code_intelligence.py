"""Code intelligence application service (Phase 7).

Parses all Python files of a repository at one revision, resolves the import /
call / instantiation / inheritance graph across files, discovers tests, and
persists the result through :class:`CodeGraphRepository`.  The service depends
only on ports + domain, so it runs against in-memory or PostgreSQL storage.

Incremental behavior (Task 7.10): ``build_revision`` replaces the facts for
the given revision in one upsert (old revision facts are expired separately),
keeping the graph revision-exact.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from brain.domain.code_intelligence import (
    CodeRelation,
    CodeRelationType,
    ImportStatement,
    ParsedFile,
    Symbol,
    SymbolKind,
    is_test_path,
)
from brain.domain.identity import RepositoryId
from brain.ports.code_intelligence import CodeGraphRepository, LanguageParser


@dataclass
class CodeIndexResult:
    repository_id: RepositoryId
    revision: str
    files_parsed: int = 0
    symbols: list[Symbol] = field(default_factory=list)
    relations: list[CodeRelation] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)


class CodeIntelligenceService:
    """Orchestrates parsing + graph resolution + persistence for a revision."""

    def __init__(
        self,
        *,
        parser: LanguageParser,
        repository: CodeGraphRepository,
    ) -> None:
        self._parser = parser
        self._repository = repository

    async def build_revision(
        self,
        repository_id: RepositoryId,
        revision: str,
        files: dict[str, str],
        *,
        replace: bool = False,
    ) -> CodeIndexResult:
        """Parse every file, resolve the graph, and persist it for the revision.

        With ``replace=True``, previous facts for the same repository+revision
        are expired first (incremental update for changed/deleted files).
        """
        if replace:
            await self._repository.expire_revision(repository_id, revision)
        parsed_files: list[ParsedFile] = []
        for path, content in files.items():
            if not path.endswith(".py"):
                continue
            parsed = await self._parser.parse(repository_id, revision, path, content)
            if parsed is not None:
                parsed_files.append(parsed)

        resolver = _GraphResolver(repository_id, revision, parsed_files)
        resolver.resolve()

        all_symbols = [symbol for parsed in parsed_files for symbol in parsed.symbols]
        all_relations = [rel for parsed in parsed_files for rel in parsed.relations]

        await self._repository.save_symbols(all_symbols)
        await self._repository.save_relations(all_relations)
        for parsed in parsed_files:
            await self._repository.save_parsed_file(parsed)

        return CodeIndexResult(
            repository_id=repository_id,
            revision=revision,
            files_parsed=len(parsed_files),
            symbols=all_symbols,
            relations=all_relations,
            test_files=[p.path for p in parsed_files if is_test_path(p.path)],
        )

    async def where_defined(
        self, repository_id: RepositoryId, revision: str, qualified_name: str
    ) -> list[Symbol]:
        return await self._repository.find_symbol(repository_id, revision, qualified_name)

    async def what_calls(
        self, repository_id: RepositoryId, revision: str, qualified_name: str
    ) -> list[CodeRelation]:
        symbols = await self._repository.find_symbol(repository_id, revision, qualified_name)
        if not symbols:
            return []
        target_keys = {symbol.identity_key for symbol in symbols}
        relations = await self._repository.list_relations(repository_id, revision)
        return [
            rel
            for rel in relations
            if rel.target_identity.key in target_keys
            and rel.relation_type == CodeRelationType.CALLS
        ]

    async def what_is_called_by(
        self, repository_id: RepositoryId, revision: str, qualified_name: str
    ) -> list[CodeRelation]:
        symbols = await self._repository.find_symbol(repository_id, revision, qualified_name)
        if not symbols:
            return []
        source_keys = {symbol.identity_key for symbol in symbols}
        relations = await self._repository.list_relations(repository_id, revision)
        return [
            rel
            for rel in relations
            if rel.source_identity.key in source_keys
            and rel.relation_type == CodeRelationType.CALLS
        ]


class _GraphResolver:
    """Resolve cross-file imports, calls and class relations (Tasks 7.4-7.7)."""

    def __init__(
        self,
        repository_id: RepositoryId,
        revision: str,
        parsed_files: list[ParsedFile],
    ) -> None:
        self._repository_id = repository_id
        self._revision = revision
        self._files = parsed_files
        self._module_to_path = {p.module: p.path for p in parsed_files}
        self._module_to_file = {p.module: p for p in parsed_files}

    def resolve(self) -> None:
        for parsed in self._files:
            self._resolve_file_imports(parsed)
            self._resolve_cross_module_calls(parsed)
            self._resolve_inheritance(parsed)
            self._resolve_test_relations(parsed)

    def _resolve_file_imports(self, parsed: ParsedFile) -> None:
        """Turn local imports into File/Module IMPORTS relations (Task 7.4)."""
        local_names: dict[str, tuple[str, str]] = {}
        for imp in parsed.imports:
            target_module = self._resolve_module(parsed.module, imp)
            if target_module is None:
                continue
            target_file = self._module_to_file.get(target_module)
            if target_file is None:
                continue
            module_symbol = self._module_symbol(target_file)
            if module_symbol is None:
                continue
            if imp.name:
                local_names[imp.alias or imp.name] = (target_module, imp.name)
            self._add_relation(
                parsed,
                CodeRelationType.IMPORTS,
                parsed_symbol=module_symbol,
                metadata={"module": target_module},
            )
        parsed.metadata["_local_names"] = local_names

    def _resolve_module(self, current_module: str, imp: ImportStatement) -> str | None:
        if not imp.is_relative:
            return imp.module if imp.module in self._module_to_path else None
        # Relative import: climb ``level`` packages from the current module.
        current_file = self._module_to_file.get(current_module)
        is_package = (
            current_file is not None and current_file.path.rsplit("/", 1)[-1] == "__init__.py"
        )
        parts = current_module.split(".")
        container = list(parts) if is_package else list(parts[:-1])
        for _ in range(imp.level - 1):
            if container:
                container.pop()
        candidate_parts = list(container)
        if imp.module:
            candidate_parts.extend(imp.module.split("."))
        candidate = ".".join(candidate_parts)
        return candidate if candidate in self._module_to_path else None

    def _resolve_cross_module_calls(self, parsed: ParsedFile) -> None:
        """Resolve calls to symbols imported from local modules (Task 7.5)."""
        local_names = parsed.metadata.get("_local_names")
        if not isinstance(local_names, dict):
            return
        class_attrs: dict[str, dict[str, str]] = {}
        for symbol in parsed.symbols:
            if symbol.kind == SymbolKind.CLASS:
                attrs = symbol.metadata.get("instance_attrs")
                if isinstance(attrs, dict):
                    class_attrs[symbol.qualified_name] = {str(k): str(v) for k, v in attrs.items()}

        for symbol in parsed.symbols:
            if symbol.kind not in {SymbolKind.FUNCTION, SymbolKind.METHOD}:
                continue
            call_sites = symbol.metadata.get("call_sites")
            if not isinstance(call_sites, list):
                continue
            for site in call_sites:
                if not isinstance(site, dict):
                    continue
                kind = site.get("kind")
                target = self._resolve_call_site(site, parsed, local_names, class_attrs, symbol)
                if target is None:
                    continue
                relation_type = CodeRelationType.CALLS
                # ``User(...)`` alone is an INSTANTIATES (constructor call).
                if kind == "name" and target.kind == SymbolKind.CLASS:
                    relation_type = CodeRelationType.INSTANTIATES
                self._add_relation(
                    parsed,
                    relation_type,
                    source_symbol=symbol,
                    target_symbol=target,
                    confidence=0.8,
                    metadata={"call_site": site.get("method") or site.get("name") or ""},
                )

    def _resolve_call_site(
        self,
        site: dict[str, str],
        parsed: ParsedFile,
        local_names: dict[str, tuple[str, str]],
        class_attrs: dict[str, dict[str, str]],
        caller: Symbol,
    ) -> Symbol | None:
        kind = site.get("kind")
        if kind == "name":
            return self._resolve_imported_name(site.get("name", ""), local_names)
        if kind == "attr_method":
            # ``mod.run(...)`` where mod was imported as a module or name.
            return self._resolve_imported_name(site.get("name", ""), local_names)
        if kind == "ctor_method":
            # ``User(...).load(...)`` -> resolve User to its module then method.
            class_symbol = self._resolve_imported_name(site.get("name", ""), local_names)
            if class_symbol is None:
                return None
            return self._find_method(class_symbol, site.get("method", ""))
        if kind == "self_method":
            # ``self.repo.get(...)`` -> repo's class from the enclosing class.
            enclosing = self._enclosing_class(caller)
            if enclosing is None:
                return None
            attr = site.get("attr", "")
            class_name = class_attrs.get(enclosing.qualified_name, {}).get(attr)
            if class_name is None:
                return None
            class_symbol = self._resolve_imported_name(class_name, local_names)
            if class_symbol is None:
                class_symbol = self._by_module_symbol(parsed.module, class_name)
            if class_symbol is None:
                return None
            return self._find_method(class_symbol, site.get("method", ""))
        return None

    def _resolve_imported_name(
        self, name: str, local_names: dict[str, tuple[str, str]]
    ) -> Symbol | None:
        resolved = local_names.get(name)
        if resolved is None:
            return None
        target_module, target_name = resolved
        # Prefer the named symbol (class/function) over the module symbol.
        if target_name:
            named = self._by_module_symbol(target_module, target_name)
            if named is not None:
                return named
        return self._module_symbol_from_module(target_module)

    def _find_method(self, class_symbol: Symbol, method: str) -> Symbol | None:
        if class_symbol.kind != SymbolKind.CLASS:
            return None
        # Search all parsed symbols for the qualified method name.
        qualified = f"{class_symbol.qualified_name}.{method}"
        for parsed in self._files:
            for symbol in parsed.symbols:
                if symbol.qualified_name == qualified and symbol.kind == SymbolKind.METHOD:
                    return symbol
        return None

    def _by_module_symbol(self, module: str, name: str) -> Symbol | None:
        target_file = self._module_to_file.get(module)
        if target_file is None:
            return None
        for symbol in target_file.symbols:
            if symbol.name == name and symbol.kind in {SymbolKind.CLASS, SymbolKind.FUNCTION}:
                return symbol
        return None

    def _enclosing_class(self, symbol: Symbol) -> Symbol | None:
        module = symbol.identity.module
        parts = symbol.qualified_name.split(".")
        # Class names appear between the module and the method name.
        if len(parts) < 3:
            return None
        class_name = parts[-2]
        target_file = self._module_to_file.get(module)
        if target_file is None:
            return None
        for s in target_file.symbols:
            if s.kind == SymbolKind.CLASS and s.name == class_name:
                return s
        return None

    def _resolve_inheritance(self, parsed: ParsedFile) -> None:
        """Cross-module INHERITS/IMPLEMENTS resolution (Task 7.6).

        Local bases are already resolved by the parser; imported bases are
        resolved here via the file's local-name map.
        """
        local_names = parsed.metadata.get("_local_names")
        if not isinstance(local_names, dict):
            return
        for symbol in parsed.symbols:
            if symbol.kind != SymbolKind.CLASS:
                continue
            bases = symbol.metadata.get("bases")
            if not isinstance(bases, list):
                continue
            for base in bases:
                if not isinstance(base, str):
                    continue
                resolved = local_names.get(base.split(".")[0])
                if resolved is None:
                    continue
                target_module, _ = resolved
                target = self._module_symbol(target_module)
                if target is None:
                    continue
                self._add_relation(
                    parsed,
                    CodeRelationType.INHERITS,
                    source_symbol=symbol,
                    target_symbol=target,
                    confidence=0.8,
                )

    def _resolve_test_relations(self, parsed: ParsedFile) -> None:
        """TESTS relations: a test module TESTS the modules it imports (Task 7.8)."""
        if not is_test_path(parsed.path):
            return
        local_names = parsed.metadata.get("_local_names")
        if not isinstance(local_names, dict):
            return
        test_module_symbol = self._module_symbol(parsed)
        if test_module_symbol is None:
            return
        seen: set[str] = set()
        for target_module, _target_name in local_names.values():
            if target_module in seen:
                continue
            seen.add(target_module)
            target = self._module_symbol_from_module(target_module)
            if target is None:
                continue
            self._add_relation(
                parsed,
                CodeRelationType.TESTS,
                parsed_symbol=test_module_symbol,
                target_symbol=target,
                confidence=0.9,
            )

    def _module_symbol(self, parsed: ParsedFile) -> Symbol | None:
        for symbol in parsed.symbols:
            if symbol.kind == SymbolKind.MODULE:
                return symbol
        return None

    def _module_symbol_from_module(self, module: str) -> Symbol | None:
        target_file = self._module_to_file.get(module)
        return self._module_symbol(target_file) if target_file is not None else None

    def _add_relation(
        self,
        parsed: ParsedFile,
        relation_type: CodeRelationType,
        *,
        parsed_symbol: Symbol | None = None,
        source_symbol: Symbol | None = None,
        target_symbol: Symbol | None = None,
        confidence: float = 1.0,
        metadata: dict[str, object] | None = None,
    ) -> None:
        source = source_symbol or self._module_symbol(parsed) or parsed_symbol
        target = target_symbol or parsed_symbol
        if source is None or target is None or source.id == target.id:
            return
        parsed.relations.append(
            CodeRelation(
                relation_type=relation_type,
                source_identity=source.identity,
                target_identity=target.identity,
                repository_id=self._repository_id,
                revision=self._revision,
                source_path=source.path,
                target_path=target.path,
                confidence=confidence,
                metadata=metadata or {},
            )
        )


__all__ = ["CodeIndexResult", "CodeIntelligenceService"]
