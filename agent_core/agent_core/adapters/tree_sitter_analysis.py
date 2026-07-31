from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_core.domain.code_analysis import SyntaxExtractionResult
from agent_core.ports.repository_analysis import SyntaxExtractionPort


class TreeSitterPythonExtractor(SyntaxExtractionPort):
    def __init__(self, *, enabled: bool = True):
        self.enabled = enabled

    def extract_python_file(
        self,
        *,
        repository_key: str,
        relative_path: str,
        absolute_path: Path,
    ) -> SyntaxExtractionResult:
        if not self.enabled:
            return _unavailable(relative_path, "Tree-sitter extraction is disabled.")

        try:
            from tree_sitter import Language, Parser
            import tree_sitter_python
        except ImportError as exc:
            return _unavailable(
                relative_path,
                f"Tree-sitter Python extraction is unavailable: {exc.name or exc}",
            )

        try:
            language = Language(tree_sitter_python.language())
            parser = Parser(language)
            source = absolute_path.read_bytes()
            tree = parser.parse(source)
            result = _extract_tree_sitter_syntax(source, tree.root_node)
            return SyntaxExtractionResult(
                available=True,
                source="tree_sitter_python",
                relative_path=relative_path,
                functions=tuple(result["functions"]),
                classes=tuple(result["classes"]),
                calls=tuple(result["calls"]),
                imports=tuple(result["imports"]),
            )
        except Exception as exc:
            return _unavailable(
                relative_path,
                f"Tree-sitter extraction failed for '{relative_path}': {type(exc).__name__}: {exc}",
            )


def _unavailable(relative_path: str, warning: str) -> SyntaxExtractionResult:
    return SyntaxExtractionResult(
        available=False,
        source="tree_sitter_python",
        relative_path=relative_path,
        warnings=(warning,),
    )


def _extract_tree_sitter_syntax(source: bytes, root_node: Any) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        "functions": [],
        "classes": [],
        "calls": [],
        "imports": [],
    }

    for node in _walk(root_node):
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                result["functions"].append(
                    {
                        "name": _node_text(source, name_node),
                        "start": _point(name_node.start_point),
                        "end": _point(name_node.end_point),
                        "range": {
                            "start": _point(node.start_point),
                            "end": _point(node.end_point),
                        },
                    }
                )
        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                result["classes"].append(
                    {
                        "name": _node_text(source, name_node),
                        "start": _point(name_node.start_point),
                        "end": _point(name_node.end_point),
                        "range": {
                            "start": _point(node.start_point),
                            "end": _point(node.end_point),
                        },
                    }
                )
        elif node.type == "call":
            function_node = node.child_by_field_name("function")
            if function_node:
                result["calls"].append(
                    {
                        "callee_text": _node_text(source, function_node),
                        "callee_node_type": function_node.type,
                        "start": _point(function_node.start_point),
                        "end": _point(function_node.end_point),
                        "full_call": _node_text(source, node),
                    }
                )
        elif node.type in {"import_statement", "import_from_statement"}:
            result["imports"].append(
                {
                    "text": _node_text(source, node),
                    "start": _point(node.start_point),
                    "end": _point(node.end_point),
                }
            )

    return result


def _walk(node: Any):
    yield node
    for child in node.children:
        yield from _walk(child)


def _node_text(source: bytes, node: Any) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8")


def _point(point: Any) -> tuple[int, int]:
    return tuple(point)
