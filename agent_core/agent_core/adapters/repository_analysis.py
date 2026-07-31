from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Iterable

from agent_core.domain.code_analysis import (
    CodeRelationship,
    CodeRelationshipKind,
    CodeSymbol,
    CodeSymbolKind,
    RepositoryIndex,
)
from agent_core.domain.repositories import (
    RepositoryAccessDenied,
    RepositoryBinding,
    UnknownRepositoryError,
    resolve_repository_path,
    resolve_repository_root,
)
from agent_core.ports.repository_analysis import (
    LspLookupPort,
    RepositoryAnalysisPort,
    SyntaxExtractionPort,
)


class PythonAstRepositoryAnalyzer(RepositoryAnalysisPort):
    def __init__(
        self,
        bindings: Iterable[RepositoryBinding],
        *,
        syntax_extractor: SyntaxExtractionPort | None = None,
        lsp_lookup: LspLookupPort | None = None,
    ):
        self._bindings = {binding.repository_key: binding for binding in bindings}
        self.syntax_extractor = syntax_extractor
        self.lsp_lookup = lsp_lookup

    async def index_repository(self, *, repository_key: str) -> RepositoryIndex:
        binding = self._get_binding(repository_key)
        root = resolve_repository_root(binding)
        symbols: list[CodeSymbol] = []
        relationships: list[CodeRelationship] = []
        warnings = []
        if self.lsp_lookup is None or not self.lsp_lookup.is_available():
            warnings.append("LSP analysis is unavailable; using deterministic Python AST fallback.")
        call_sites: list[_CallSite] = []

        for path in sorted(root.rglob("*.py")):
            relative_path = path.relative_to(root).as_posix()
            try:
                resolved = resolve_repository_path(binding, relative_path)
            except (RepositoryAccessDenied, OSError) as exc:
                warnings.append(f"Skipped denied repository path '{relative_path}': {exc}")
                continue

            if not resolved.absolute_path.is_file():
                continue

            syntax_metadata: dict = {}
            if self.syntax_extractor is not None:
                syntax = self.syntax_extractor.extract_python_file(
                    repository_key=repository_key,
                    relative_path=relative_path,
                    absolute_path=resolved.absolute_path,
                )
                warnings.extend(syntax.warnings)
                if syntax.available:
                    syntax_metadata = {
                        "syntax_source": syntax.source,
                        "tree_sitter_function_count": len(syntax.functions),
                        "tree_sitter_class_count": len(syntax.classes),
                        "tree_sitter_call_count": len(syntax.calls),
                        "tree_sitter_import_count": len(syntax.imports),
                    }

            source = resolved.absolute_path.read_text(encoding="utf-8")
            file_symbol = CodeSymbol(
                symbol_key=_file_symbol_key(repository_key, relative_path),
                repository_key=repository_key,
                relative_path=relative_path,
                name=relative_path,
                kind=CodeSymbolKind.FILE,
                language="python",
                metadata=syntax_metadata,
            )
            symbols.append(file_symbol)

            try:
                tree = ast.parse(source, filename=relative_path)
            except SyntaxError as exc:
                warnings.append(f"Skipped Python syntax error in '{relative_path}': {exc}")
                continue

            visitor = _PythonSymbolVisitor(
                repository_key=repository_key,
                relative_path=relative_path,
                file_symbol_key=file_symbol.symbol_key,
            )
            visitor.visit(tree)
            symbols.extend(visitor.symbols)
            relationships.extend(visitor.relationships)
            call_sites.extend(visitor.call_sites)

        relationships.extend(_resolve_call_relationships(repository_key, symbols, call_sites))

        return RepositoryIndex(
            repository_key=repository_key,
            symbols=tuple(symbols),
            relationships=tuple(relationships),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def _get_binding(self, repository_key: str) -> RepositoryBinding:
        try:
            return self._bindings[repository_key]
        except KeyError as exc:
            raise UnknownRepositoryError(f"Unknown repository: {repository_key}") from exc


class _PythonSymbolVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        repository_key: str,
        relative_path: str,
        file_symbol_key: str,
    ) -> None:
        self.repository_key = repository_key
        self.relative_path = relative_path
        self.file_symbol_key = file_symbol_key
        self.symbols: list[CodeSymbol] = []
        self.relationships: list[CodeRelationship] = []
        self.call_sites: list[_CallSite] = []
        self._symbol_stack: list[CodeSymbol] = []
        self._qualname_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_definition(node, CodeSymbolKind.CLASS)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_definition(node, CodeSymbolKind.FUNCTION)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_definition(node, CodeSymbolKind.FUNCTION)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record_import(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        for alias in node.names:
            imported_name = f"{module}.{alias.name}".strip(".")
            self._record_import(imported_name, node.lineno)

    def visit_Call(self, node: ast.Call) -> None:
        source_symbol = self._current_symbol_key()
        callee_name = _call_name(node.func)
        if source_symbol and callee_name:
            self.call_sites.append(
                _CallSite(
                    source_symbol_key=source_symbol,
                    callee_name=callee_name,
                    line_number=node.lineno,
                )
            )
        self.generic_visit(node)

    def _visit_definition(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        kind: CodeSymbolKind,
    ) -> None:
        qualname = ".".join([*self._qualname_stack, node.name])
        parent_symbol_key = self._current_symbol_key()
        symbol = CodeSymbol(
            symbol_key=_symbol_key(
                self.repository_key,
                kind.value,
                self.relative_path,
                qualname,
                node.lineno,
            ),
            repository_key=self.repository_key,
            relative_path=self.relative_path,
            name=node.name,
            kind=kind,
            language="python",
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", None),
            parent_symbol_key=parent_symbol_key,
            metadata={"qualname": qualname},
        )
        self.symbols.append(symbol)
        self.relationships.append(
            CodeRelationship(
                repository_key=self.repository_key,
                source_symbol_key=parent_symbol_key or self.file_symbol_key,
                target_symbol_key=symbol.symbol_key,
                target_name=symbol.name,
                relationship_type=CodeRelationshipKind.DEFINES,
            )
        )

        self._symbol_stack.append(symbol)
        self._qualname_stack.append(node.name)
        self.generic_visit(node)
        self._qualname_stack.pop()
        self._symbol_stack.pop()

    def _record_import(self, imported_name: str, line_number: int) -> None:
        symbol = CodeSymbol(
            symbol_key=_symbol_key(
                self.repository_key,
                CodeSymbolKind.IMPORT.value,
                self.relative_path,
                imported_name,
                line_number,
            ),
            repository_key=self.repository_key,
            relative_path=self.relative_path,
            name=imported_name,
            kind=CodeSymbolKind.IMPORT,
            language="python",
            start_line=line_number,
            end_line=line_number,
        )
        self.symbols.append(symbol)
        self.relationships.append(
            CodeRelationship(
                repository_key=self.repository_key,
                source_symbol_key=self._current_symbol_key() or self.file_symbol_key,
                target_symbol_key=symbol.symbol_key,
                target_name=imported_name,
                relationship_type=CodeRelationshipKind.IMPORTS,
            )
        )

    def _current_symbol_key(self) -> str | None:
        if not self._symbol_stack:
            return None
        return self._symbol_stack[-1].symbol_key


class _CallSite:
    def __init__(self, *, source_symbol_key: str, callee_name: str, line_number: int):
        self.source_symbol_key = source_symbol_key
        self.callee_name = callee_name
        self.line_number = line_number


def _resolve_call_relationships(
    repository_key: str,
    symbols: list[CodeSymbol],
    call_sites: list[_CallSite],
) -> list[CodeRelationship]:
    symbols_by_name: dict[str, list[CodeSymbol]] = defaultdict(list)
    for symbol in symbols:
        if symbol.kind in {CodeSymbolKind.FUNCTION, CodeSymbolKind.CLASS}:
            symbols_by_name[symbol.name].append(symbol)

    relationships: list[CodeRelationship] = []
    for call_site in call_sites:
        target_name = call_site.callee_name.rsplit(".", 1)[-1]
        candidates = symbols_by_name.get(target_name, [])
        if len(candidates) == 1:
            relationships.append(
                CodeRelationship(
                    repository_key=repository_key,
                    source_symbol_key=call_site.source_symbol_key,
                    target_symbol_key=candidates[0].symbol_key,
                    target_name=call_site.callee_name,
                    relationship_type=CodeRelationshipKind.CALLS,
                    metadata={"line_number": call_site.line_number},
                )
            )
        else:
            relationships.append(
                CodeRelationship(
                    repository_key=repository_key,
                    source_symbol_key=call_site.source_symbol_key,
                    target_name=call_site.callee_name,
                    relationship_type=CodeRelationshipKind.UNRESOLVED_CALL,
                    metadata={"line_number": call_site.line_number},
                )
            )
    return relationships


def _file_symbol_key(repository_key: str, relative_path: str) -> str:
    return _symbol_key(repository_key, CodeSymbolKind.FILE.value, relative_path, relative_path, 1)


def _symbol_key(
    repository_key: str,
    kind: str,
    relative_path: str,
    name: str,
    line_number: int,
) -> str:
    return f"{repository_key}:{kind}:{relative_path}:{name}:{line_number}"


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
        return node.attr
    return None
