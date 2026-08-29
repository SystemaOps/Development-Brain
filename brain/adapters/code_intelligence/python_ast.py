"""Python AST code parser (Task 7.2).

Uses :mod:`ast` to extract modules, classes, functions, methods, imports,
decorators, parameters and return annotations into the canonical
:class:`~brain.domain.code_intelligence.ParsedFile` model.  The parser is pure
and deterministic: same content at the same revision always yields the same
symbols and relations.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

from brain.domain.code_intelligence import (
    CodeRelation,
    CodeRelationType,
    ImportStatement,
    ParsedFile,
    Symbol,
    SymbolIdentity,
    SymbolKind,
    SymbolLocation,
    content_hash,
    module_from_path,
)
from brain.domain.identity import RepositoryId


class PythonAstParser:
    """Parse Python source into canonical :class:`ParsedFile` (Task 7.2)."""

    LANGUAGE = "python"

    async def parse(
        self,
        repository_id: RepositoryId,
        revision: str,
        path: str,
        content: str,
    ) -> ParsedFile | None:
        try:
            tree = ast.parse(content, filename=path)
        except SyntaxError:
            return None

        module = module_from_path(path)
        parsed = ParsedFile(
            path=path,
            module=module,
            language=self.LANGUAGE,
            repository_id=repository_id,
            revision=revision,
            content_hash=content_hash(content),
        )

        builder = _FileBuilder(repository_id, revision, path, module)
        parsed.symbols = builder.build(tree, content)
        parsed.imports = builder.imports
        parsed.relations = builder.relations
        return parsed


class _FileBuilder:
    def __init__(
        self,
        repository_id: RepositoryId,
        revision: str,
        path: str,
        module: str,
    ) -> None:
        self._repository_id = repository_id
        self._revision = revision
        self._path = path
        self._module = module
        self.symbols: list[Symbol] = []
        self.imports: list[ImportStatement] = []
        self.relations: list[CodeRelation] = []
        self._by_qualified: dict[str, Symbol] = {}
        self._pending: list[tuple[Symbol, list[ast.stmt]]] = []

    def _identity(self, qualified_name: str, kind: SymbolKind) -> SymbolIdentity:
        return SymbolIdentity(
            repository_id=self._repository_id,
            revision=self._revision,
            module=self._module,
            qualified_name=qualified_name,
            kind=kind,
        )

    def _add_symbol(
        self,
        name: str,
        qualified_name: str,
        kind: SymbolKind,
        node: ast.AST,
        *,
        parameters: list[str] | None = None,
        return_annotation: str | None = None,
        decorators: list[str] | None = None,
        docstring: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Symbol:
        symbol = Symbol(
            identity=self._identity(qualified_name, kind),
            name=name,
            path=self._path,
            kind=kind,
            location=_location(self._path, node),
            qualified_name=qualified_name,
            parameters=parameters or [],
            return_annotation=return_annotation,
            decorators=decorators or [],
            docstring=docstring,
            metadata=metadata or {},
        )
        self.symbols.append(symbol)
        self._by_qualified[qualified_name] = symbol
        return symbol

    def _add_relation(
        self,
        relation_type: CodeRelationType,
        source: Symbol | None,
        target: Symbol | None,
        *,
        source_identity: SymbolIdentity | None = None,
        target_identity: SymbolIdentity | None = None,
        confidence: float = 1.0,
        metadata: dict[str, object] | None = None,
    ) -> None:
        src = source_identity or (source.identity if source else None)
        tgt = target_identity or (target.identity if target else None)
        if src is None or tgt is None:
            return
        self.relations.append(
            CodeRelation(
                relation_type=relation_type,
                source_identity=src,
                target_identity=tgt,
                repository_id=self._repository_id,
                revision=self._revision,
                source_path=self._path,
                target_path=self._path,
                confidence=confidence,
                metadata=metadata or {},
            )
        )

    def build(self, tree: ast.Module, content: str) -> list[Symbol]:
        module_docstring = ast.get_docstring(tree)
        module_symbol = self._add_symbol(
            self._module.split(".")[-1] or self._path,
            self._module,
            SymbolKind.MODULE,
            tree,
            docstring=module_docstring,
        )

        for node in tree.body:
            if isinstance(node, ast.Import):
                self._handle_import(node, is_relative=False)
            elif isinstance(node, ast.ImportFrom):
                self._handle_import(node, is_relative=node.level > 0)
            elif isinstance(node, ast.ClassDef):
                self._handle_class(node, module_symbol)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._handle_function(node, module_symbol, kind=SymbolKind.FUNCTION)

        # Cross-file relations are resolved later (import graph); here we keep
        # intra-file calls/class relations already emitted by the handlers.
        # Resolve pending call sites now that every module symbol is known
        # (handles forward references like a later-defined function).
        for caller, body in self._pending:
            self._extract_calls(body, caller)
            self._extract_instantiations(body, caller)
        self._pending.clear()
        return self.symbols

    def _handle_import(self, node: ast.AST, *, is_relative: bool) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                self._record_import(alias.name, None, alias.asname, is_relative, 0, node)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                self._record_import(module, alias.name, alias.asname, is_relative, node.level, node)

    def _record_import(
        self,
        module: str,
        name: str | None,
        alias: str | None,
        is_relative: bool,
        level: int,
        node: ast.AST,
    ) -> None:
        self.imports.append(
            ImportStatement(
                module=module,
                name=name,
                alias=alias,
                is_relative=is_relative,
                level=level,
                is_local=None,
                location=_location(self._path, node),
            )
        )
        # The import itself is a symbol of the current module.
        target_name = alias or name or module.split(".")[-1]
        qualified = f"{self._module}.{target_name}"
        import_symbol = self._add_symbol(
            target_name,
            qualified,
            SymbolKind.IMPORT,
            node,
            metadata={"import_module": module, "import_name": name or ""},
        )
        # Module-level relation: this file IMPORTS the module.
        module_symbol = self._by_qualified.get(self._module)
        if module_symbol is not None:
            self._add_relation(
                CodeRelationType.IMPORTS,
                module_symbol,
                import_symbol,
                metadata={"import_module": module},
            )

    def _handle_class(self, node: ast.ClassDef, parent: Symbol | None) -> None:
        qualified = f"{self._module}.{node.name}"
        docstring = ast.get_docstring(node)
        bases = [_unparse(base) for base in node.bases]
        class_symbol = self._add_symbol(
            node.name,
            qualified,
            SymbolKind.CLASS,
            node,
            docstring=docstring,
            metadata={"bases": bases, "instance_attrs": _instance_attrs(node.body)},
        )
        # INHERITS relations from declared base classes (resolved locally only
        # when the base class exists in the same module).
        for base in bases:
            base_qualified = f"{self._module}.{base}"
            base_symbol = self._by_qualified.get(base_qualified)
            if base_symbol is not None and base_symbol.id != class_symbol.id:
                self._add_relation(
                    CodeRelationType.INHERITS,
                    class_symbol,
                    base_symbol,
                    metadata={"base": base},
                )

        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._handle_function(item, class_symbol, kind=SymbolKind.METHOD)

    def _handle_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        parent: Symbol | None,
        *,
        kind: SymbolKind,
    ) -> None:
        qualified = f"{self._module}.{node.name}"
        if parent is not None and parent.kind in {SymbolKind.CLASS, SymbolKind.METHOD}:
            qualified = f"{parent.qualified_name}.{node.name}"
        parameters = [_unparse(a) for a in node.args.args]
        return_annotation = _unparse(node.returns) if node.returns is not None else None
        decorators = [_unparse(d) for d in node.decorator_list]
        docstring = ast.get_docstring(node)

        function_symbol = self._add_symbol(
            node.name,
            qualified,
            kind,
            node,
            parameters=parameters,
            return_annotation=return_annotation,
            decorators=decorators,
            docstring=docstring,
            metadata={
                "referenced": _referenced_names(node.body),
                "call_sites": _call_sites(node.body),
            },
        )

        if (
            parent is not None
            and kind == SymbolKind.METHOD
            and node.name in {"__init__", "__new__"}
        ):
            # No CALLS relation from constructor; keep simple.
            pass
        self._pending.append((function_symbol, node.body))

    def _extract_calls(self, body: list[ast.stmt], caller: Symbol) -> None:
        for item in _walk(body):
            if not isinstance(item, ast.Call):
                continue
            func = item.func
            if isinstance(func, ast.Name):
                target = self._by_qualified.get(f"{self._module}.{func.id}")
                if target is not None:
                    self._add_relation(CodeRelationType.CALLS, caller, target)
            elif isinstance(func, ast.Attribute):
                target = self._by_qualified.get(f"{self._module}.{_attr_name(func)}")
                if target is not None:
                    self._add_relation(CodeRelationType.CALLS, caller, target)

    def _extract_instantiations(self, body: list[ast.stmt], caller: Symbol) -> None:
        for item in _walk(body):
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Name):
                target = self._by_qualified.get(f"{self._module}.{item.func.id}")
                if target is not None and target.kind == SymbolKind.CLASS:
                    self._add_relation(CodeRelationType.INSTANTIATES, caller, target)


def _referenced_names(body: list[ast.stmt]) -> list[str]:
    """Simple call-target names a function body references (for cross-module
    call resolution).  Keeps only bare ``Name`` call targets; attribute chains
    like ``models.User(...)`` are handled separately by local-name resolution.
    """
    names: list[str] = []
    for node in body:
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                names.append(child.func.id)
    return names


def _instance_attrs(body: list[ast.stmt]) -> dict[str, str]:
    """Instance attributes assigned in a class body, e.g. ``self.repo = UserRepository()``.

    Returns ``{attr: assigned_name}`` so call resolution can map
    ``self.repo.get(...)`` to ``UserRepository.get``.
    """
    attrs: dict[str, str] = {}
    for node in body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Assign):
                continue
            for target in child.targets:
                if not (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    continue
                value = child.value
                if isinstance(value, ast.Name):
                    attrs[target.attr] = value.id
                elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                    attrs[target.attr] = value.func.id
    return attrs


def _call_sites(body: list[ast.stmt]) -> list[dict[str, str]]:
    """Structured call sites for cross-module call resolution.

    Each site is a dict describing the callee shape:
    - ``{"kind": "name", "name": "get_user"}``             -> ``get_user(...)``
    - ``{"kind": "self_method", "attr": "repo", "method": "get"}``
      -> ``self.repo.get(...)``
    - ``{"kind": "ctor_method", "name": "User", "method": "load"}``
      -> ``User(...).load(...)``
    - ``{"kind": "attr_method", "name": "mod", "method": "run"}``
      -> ``mod.run(...)``
    """
    sites: list[dict[str, str]] = []
    for node in body:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if isinstance(func, ast.Name):
                sites.append({"kind": "name", "name": func.id})
                continue
            if isinstance(func, ast.Attribute):
                value = func.value
                if (
                    isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "self"
                ):
                    sites.append({"kind": "self_method", "attr": value.attr, "method": func.attr})
                elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                    sites.append(
                        {"kind": "ctor_method", "name": value.func.id, "method": func.attr}
                    )
                elif isinstance(value, ast.Name):
                    sites.append({"kind": "attr_method", "name": value.id, "method": func.attr})
    return sites


def _walk(nodes: list[ast.stmt]) -> Iterator[ast.AST]:
    for node in nodes:
        yield from ast.walk(node)


def _location(path: str, node: ast.AST) -> SymbolLocation:
    end_lineno = getattr(node, "end_lineno", None)
    end_col_offset = getattr(node, "end_col_offset", None)
    return SymbolLocation(
        path=path,
        start_line=getattr(node, "lineno", 0) or 0,
        start_column=getattr(node, "col_offset", 0) or 0,
        end_line=end_lineno or 0,
        end_column=end_col_offset or 0,
    )


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _attr_name(node: ast.Attribute) -> str:
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


__all__ = ["PythonAstParser"]
