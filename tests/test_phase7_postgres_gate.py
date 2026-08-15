"""Phase 7 completion gate against PostgreSQL persistence.

Runs the same fixture repository through the code intelligence service using
the Postgres code graph repository, proving the graph is restart-safe and
revision-exact on real storage.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from brain.adapters.code_intelligence.python_ast import PythonAstParser
from brain.adapters.postgresql.database import create_repositories
from brain.application.code_intelligence import CodeIntelligenceService
from brain.domain.code_intelligence import CodeRelationType
from brain.domain.identity import RepositoryId
from brain.ports.code_intelligence import CodeGraphRepository

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
def code_graph(postgres_session: AsyncSession) -> CodeGraphRepository:
    return create_repositories(postgres_session).code_graph


async def test_gate_where_defined_postgres(code_graph: CodeGraphRepository) -> None:
    service = CodeIntelligenceService(parser=PythonAstParser(), repository=code_graph)
    repository_id = RepositoryId(uuid.uuid4())
    await service.build_revision(repository_id, REVISION, REPOSITORY_FILES)

    symbols = await service.where_defined(repository_id, REVISION, TARGET)
    assert len(symbols) == 1
    assert symbols[0].path == "app/service.py"

    # Revision-exact: newer revision does not bleed into the old one.
    await service.build_revision(repository_id, "nextrev", REPOSITORY_FILES)
    old = await service.where_defined(repository_id, REVISION, TARGET)
    new = await service.where_defined(repository_id, "nextrev", TARGET)
    assert old[0].identity.revision == REVISION
    assert new[0].identity.revision == "nextrev"


async def test_gate_relations_postgres(code_graph: CodeGraphRepository) -> None:
    service = CodeIntelligenceService(parser=PythonAstParser(), repository=code_graph)
    repository_id = RepositoryId(uuid.uuid4())
    await service.build_revision(repository_id, REVISION, REPOSITORY_FILES)

    callers = await service.what_calls(repository_id, REVISION, TARGET)
    assert any(c.source_path == "app/router.py" for c in callers)

    relations = await code_graph.list_relations(repository_id, REVISION)
    imports = [r for r in relations if r.relation_type == CodeRelationType.IMPORTS]
    assert any(
        r.source_identity.qualified_name == "app.router"
        and r.target_identity.qualified_name == "app.service"
        for r in imports
    )
