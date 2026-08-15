"""Unit tests for the Python AST parser (Task 7.2)."""

from __future__ import annotations

import uuid

from brain.adapters.code_intelligence.python_ast import PythonAstParser
from brain.domain.code_intelligence import (
    CodeRelationType,
    ParsedFile,
    SymbolKind,
)
from brain.domain.identity import RepositoryId

REVISION = "abc123"


def _repository_id() -> RepositoryId:
    return RepositoryId(uuid.uuid4())


async def _parse(content: str, path: str = "app/service.py") -> ParsedFile:
    parsed = await PythonAstParser().parse(_repository_id(), REVISION, path, content)
    assert parsed is not None
    return parsed


async def test_parses_module_function_and_class() -> None:
    parsed = await _parse(
        """
class AuthService:
    def login(self, username: str) -> bool:
        return True

def helper() -> None:
    pass
"""
    )
    kinds = {symbol.kind for symbol in parsed.symbols}
    assert SymbolKind.MODULE in kinds
    assert SymbolKind.CLASS in kinds
    assert SymbolKind.METHOD in kinds
    assert SymbolKind.FUNCTION in kinds

    login = next(s for s in parsed.symbols if s.name == "login")
    assert login.qualified_name == "app.service.AuthService.login"
    assert login.parameters == ["self", "username: str"]
    assert login.return_annotation == "bool"


async def test_parses_imports_with_metadata() -> None:
    parsed = await _parse(
        """
import os
from . import models
from .models import User
"""
    )
    assert len(parsed.imports) == 3
    assert parsed.imports[0].module == "os"
    assert parsed.imports[0].is_relative is False
    assert parsed.imports[1].is_relative is True
    assert parsed.imports[2].name == "User"


async def test_resolves_intra_module_call() -> None:
    parsed = await _parse(
        """
def get_user(uid: str) -> str:
    return uid

def handle(uid: str) -> str:
    return get_user(uid)
"""
    )
    calls = [r for r in parsed.relations if r.relation_type == CodeRelationType.CALLS]
    assert any(
        r.source_identity.qualified_name == "app.service.handle"
        and r.target_identity.qualified_name == "app.service.get_user"
        for r in calls
    )


async def test_resolves_forward_reference_call() -> None:
    parsed = await _parse(
        """
def handle(uid: str) -> str:
    return get_user(uid)

def get_user(uid: str) -> str:
    return uid
"""
    )
    calls = [r for r in parsed.relations if r.relation_type == CodeRelationType.CALLS]
    assert any(
        r.source_identity.qualified_name == "app.service.handle"
        and r.target_identity.qualified_name == "app.service.get_user"
        for r in calls
    )


async def test_resolves_local_inheritance() -> None:
    parsed = await _parse(
        """
class Base:
    pass

class Derived(Base):
    pass
"""
    )
    inherits = [r for r in parsed.relations if r.relation_type == CodeRelationType.INHERITS]
    assert any(
        r.source_identity.qualified_name == "app.service.Derived"
        and r.target_identity.qualified_name == "app.service.Base"
        for r in inherits
    )


async def test_records_docstring_and_decorators() -> None:
    parsed = await _parse(
        """
def run() -> None:
    "Runs the service."
    pass
"""
    )
    run = next(s for s in parsed.symbols if s.name == "run")
    assert run.docstring == "Runs the service."


async def test_returns_none_for_syntax_error() -> None:
    parsed = await PythonAstParser().parse(_repository_id(), REVISION, "app/broken.py", "def (")
    assert parsed is None


async def test_module_from_package_init() -> None:
    parsed = await _parse("# empty", path="app/__init__.py")
    assert parsed.module == "app"


async def test_decorators_extracted() -> None:
    parsed = await _parse(
        """
import functools

@functools.lru_cache
def cached() -> str:
    return "x"
"""
    )
    cached = next(s for s in parsed.symbols if s.name == "cached")
    assert cached.decorators == ["functools.lru_cache"]


async def test_instantiates_relation() -> None:
    parsed = await _parse(
        """
class User:
    pass

def make_user() -> User:
    return User()
"""
    )
    instantiates = [r for r in parsed.relations if r.relation_type == CodeRelationType.INSTANTIATES]
    assert any(
        r.source_identity.qualified_name == "app.service.make_user"
        and r.target_identity.qualified_name == "app.service.User"
        for r in instantiates
    )
