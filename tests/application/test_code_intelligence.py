"""Unit tests for the code intelligence + impact analysis services (Phase 7)."""

from __future__ import annotations

import uuid

import pytest

from brain.adapters.code_intelligence.python_ast import PythonAstParser
from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.application.code_intelligence import CodeIntelligenceService
from brain.application.impact_analysis import ImpactAnalysisService
from brain.domain.code_intelligence import CodeRelationType
from brain.domain.identity import RepositoryId

REVISION = "abc123"


def _repository_id() -> RepositoryId:
    return RepositoryId(uuid.uuid4())


def _fixture_repository() -> dict[str, str]:
    """The fixture repo from Task 7.12: router -> service -> repository -> model."""
    return {
        "app/__init__.py": "",
        "app/models.py": """
class User:
    def __init__(self, uid: str) -> None:
        self.uid = uid
""",
        "app/repository.py": """
from .models import User

class UserRepository:
    def get(self, uid: str) -> User:
        return User(uid=uid)
""",
        "app/service.py": """
from .models import User
from .repository import UserRepository

class AuthService:
    def __init__(self) -> None:
        self.repo = UserRepository()

    def login(self, uid: str) -> User:
        return self.repo.get(uid)
""",
        "app/router.py": """
from .service import AuthService

def handle_login(uid: str) -> None:
    AuthService().login(uid)
""",
        "tests/test_auth.py": """
from app.service import AuthService

def test_login_returns_user() -> None:
    assert AuthService().login("u1").uid == "u1"
""",
    }


@pytest.fixture
def code_service() -> tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService]:
    repository = InMemoryCodeGraphRepository()
    service = CodeIntelligenceService(
        parser=PythonAstParser(),
        repository=repository,
    )
    return _repository_id(), repository, service


async def test_build_revision_parses_all_python_files(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    result = await service.build_revision(repository_id, REVISION, _fixture_repository())
    assert result.files_parsed == 6
    assert len(result.symbols) > 10
    assert sorted(result.test_files) == ["tests/test_auth.py"]


async def test_import_graph_resolves_local_modules(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, _fixture_repository())
    relations = await repository.list_relations(repository_id, REVISION)
    imports = [r for r in relations if r.relation_type == CodeRelationType.IMPORTS]
    imported_modules = {r.metadata.get("module") for r in imports}
    assert "app.models" in imported_modules
    assert "app.repository" in imported_modules
    assert "app.service" in imported_modules


async def test_cross_module_call_resolution(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, _fixture_repository())
    relations = await repository.list_relations(repository_id, REVISION)
    calls = [r for r in relations if r.relation_type == CodeRelationType.CALLS]
    # service.AuthService.login -> repository.UserRepository.get
    assert any(
        r.source_identity.qualified_name == "app.service.AuthService.login"
        and r.target_identity.qualified_name == "app.repository.UserRepository.get"
        for r in calls
    )
    # router.handle_login -> service.AuthService.login
    assert any(
        r.source_identity.qualified_name == "app.router.handle_login"
        and r.target_identity.qualified_name == "app.service.AuthService.login"
        for r in calls
    )


async def test_where_defined_query(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, _fixture_repository())
    symbols = await service.where_defined(repository_id, REVISION, "app.service.AuthService.login")
    assert len(symbols) == 1
    assert symbols[0].path == "app/service.py"


async def test_what_calls_and_called_by(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, _fixture_repository())

    callers = await service.what_calls(repository_id, REVISION, "app.service.AuthService.login")
    assert len(callers) >= 1
    assert any(c.source_identity.qualified_name == "app.router.handle_login" for c in callers)

    callees = await service.what_is_called_by(
        repository_id, REVISION, "app.service.AuthService.login"
    )
    assert len(callees) >= 1
    assert any(
        c.target_identity.qualified_name == "app.repository.UserRepository.get" for c in callees
    )


async def test_incremental_build_overwrites_revision(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, _fixture_repository())
    # Build a different revision with a different file set; the old revision
    # facts remain, the new ones are added without duplication.
    await service.build_revision(
        repository_id, "nextrev", {"app/other.py": "def f() -> None:\n    pass\n"}
    )
    old = await repository.list_symbols(repository_id, REVISION)
    new = await repository.list_symbols(repository_id, "nextrev")
    assert len(old) > 10
    assert len(new) == 2  # module + function


async def test_impact_analysis_returns_expected_neighborhood(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, _fixture_repository())

    impact = ImpactAnalysisService(repository=repository)
    result = await impact.analyze(
        repository_id, REVISION, target_symbols=["app.service.AuthService.login"]
    )

    assert len(result.primary_symbols) == 1
    assert result.primary_symbols[0].qualified_name == "app.service.AuthService.login"

    # direct dependents: router.handle_login calls it.
    assert any(
        r.source_identity.qualified_name == "app.router.handle_login"
        for r in result.direct_dependents
    )

    # reverse: it calls repository.UserRepository.get.
    assert any(
        r.target_identity.qualified_name == "app.repository.UserRepository.get"
        for r in result.reverse_dependencies
    )

    assert "app/router.py" in result.related_files
    assert "app/service.py" in result.related_files
    assert "tests/test_auth.py" in result.related_tests
    assert result.risk_score > 0.0


async def test_impact_analysis_unknown_target_returns_empty(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, _fixture_repository())
    impact = ImpactAnalysisService(repository=repository)
    result = await impact.analyze(repository_id, REVISION, target_symbols=["app.nope.Missing"])
    assert result.primary_symbols == []
    assert result.risk_score == 0.0
