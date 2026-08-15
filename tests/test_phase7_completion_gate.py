"""Phase 7 golden tests and completion gate.

Given a fixture repository (router -> service -> repository -> model + tests),
for a selected function at an exact revision the system answers:
where is it defined, what does it call, what calls it, which files are
related, which tests are related -- all revision-exact.
"""

from __future__ import annotations

import uuid

import pytest

from brain.adapters.code_intelligence.python_ast import PythonAstParser
from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.application.code_intelligence import CodeIntelligenceService
from brain.application.impact_analysis import ImpactAnalysisService
from brain.domain.code_intelligence import CodeRelationType
from brain.domain.identity import RepositoryId

REVISION = "deadbeef"
TARGET = "app.service.AuthService.login"

REPOSITORY_FILES: dict[str, str] = {
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
    return RepositoryId(uuid.uuid4()), repository, service


async def test_gate_where_defined(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, REPOSITORY_FILES)
    symbols = await service.where_defined(repository_id, REVISION, TARGET)
    assert len(symbols) == 1
    symbol = symbols[0]
    assert symbol.path == "app/service.py"
    assert symbol.kind.value == "method"
    assert symbol.identity.revision == REVISION


async def test_gate_what_it_calls(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, REPOSITORY_FILES)
    callees = await service.what_is_called_by(repository_id, REVISION, TARGET)
    # AuthService.login calls UserRepository.get via self.repo.
    assert any(
        c.target_identity.qualified_name == "app.repository.UserRepository.get" for c in callees
    )
    # UserRepository.get constructs User via INSTANTIATES.
    relations = await repository.list_relations(repository_id, REVISION)
    instantiates = [r for r in relations if r.relation_type == CodeRelationType.INSTANTIATES]
    assert any(
        r.source_identity.qualified_name == "app.repository.UserRepository.get"
        and r.target_identity.qualified_name == "app.models.User"
        for r in instantiates
    )


async def test_gate_what_calls_it(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, REPOSITORY_FILES)
    callers = await service.what_calls(repository_id, REVISION, TARGET)
    assert any(c.source_identity.qualified_name == "app.router.handle_login" for c in callers)
    # The test also calls it.
    assert any(
        c.source_path == "tests/test_auth.py" and c.target_path == "app/service.py" for c in callers
    )


async def test_gate_related_files_and_tests(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, REPOSITORY_FILES)
    impact = ImpactAnalysisService(repository=repository)
    result = await impact.analyze(repository_id, REVISION, target_symbols=[TARGET])

    assert "app/service.py" in result.related_files
    assert "app/router.py" in result.related_files
    assert "app/repository.py" in result.related_files
    assert "tests/test_auth.py" in result.related_tests
    assert result.risk_score > 0.0


async def test_gate_is_revision_exact(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, REPOSITORY_FILES)
    # A newer revision with the same symbol still keeps old-revision facts.
    await service.build_revision(repository_id, "nextrev", REPOSITORY_FILES)
    old = await service.where_defined(repository_id, REVISION, TARGET)
    new = await service.where_defined(repository_id, "nextrev", TARGET)
    assert len(old) == 1
    assert len(new) == 1
    assert old[0].identity.revision == REVISION
    assert new[0].identity.revision == "nextrev"
    assert old[0].identity_key != new[0].identity_key


async def test_gate_answers_via_import_graph(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, REPOSITORY_FILES)
    relations = await repository.list_relations(repository_id, REVISION)
    imports = [r for r in relations if r.relation_type == CodeRelationType.IMPORTS]
    assert any(
        r.source_identity.qualified_name == "app.router"
        and r.target_identity.qualified_name == "app.service"
        for r in imports
    )


async def test_gate_unknown_symbol_is_empty(
    code_service: tuple[RepositoryId, InMemoryCodeGraphRepository, CodeIntelligenceService],
) -> None:
    repository_id, repository, service = code_service
    await service.build_revision(repository_id, REVISION, REPOSITORY_FILES)
    assert await service.where_defined(repository_id, REVISION, "app.service.nope") == []
    impact = ImpactAnalysisService(repository=repository)
    result = await impact.analyze(repository_id, REVISION, target_symbols=["app.service.nope"])
    assert result.primary_symbols == []
    assert result.risk_score == 0.0
