"""CodeGraphRepository contract."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.code_intelligence import (
    CodeRelation,
    CodeRelationType,
    ParsedFile,
    Symbol,
    SymbolIdentity,
    SymbolKind,
    SymbolLocation,
)
from brain.domain.identity import RepositoryId
from brain.ports.code_intelligence import CodeGraphRepository


def _repository_id() -> RepositoryId:
    return RepositoryId(uuid.uuid4())


def _symbol(
    repository_id: RepositoryId,
    revision: str,
    qualified_name: str,
    kind: SymbolKind = SymbolKind.FUNCTION,
    module: str = "app.service",
) -> Symbol:
    return Symbol(
        identity=SymbolIdentity(
            repository_id=repository_id,
            revision=revision,
            module=module,
            qualified_name=qualified_name,
            kind=kind,
        ),
        name=qualified_name.rsplit(".", 1)[-1],
        path="app/service.py",
        kind=kind,
        location=SymbolLocation(path="app/service.py", start_line=1),
        qualified_name=qualified_name,
        parameters=["x"],
    )


class CodeGraphRepositoryContract:
    @pytest.fixture
    def code_graph_repository(self) -> CodeGraphRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, code_graph_repository: CodeGraphRepository) -> None:
        assert isinstance(code_graph_repository, CodeGraphRepository)

    async def test_symbol_round_trip(self, code_graph_repository: CodeGraphRepository) -> None:
        repository_id = _repository_id()
        symbol = _symbol(repository_id, "abc", "app.service.run")
        await code_graph_repository.save_symbols([symbol])
        stored = await code_graph_repository.get_symbol(repository_id, "abc", symbol.identity_key)
        assert stored is not None
        assert stored.qualified_name == "app.service.run"
        assert stored.identity.repository_id == repository_id

    async def test_list_symbols_scoped_to_revision(
        self, code_graph_repository: CodeGraphRepository
    ) -> None:
        repository_id = _repository_id()
        symbol = _symbol(repository_id, "abc", "app.service.run")
        await code_graph_repository.save_symbols([symbol])
        assert len(await code_graph_repository.list_symbols(repository_id, "abc")) == 1
        assert await code_graph_repository.list_symbols(repository_id, "def") == []

    async def test_find_symbol_by_qualified_name(
        self, code_graph_repository: CodeGraphRepository
    ) -> None:
        repository_id = _repository_id()
        symbol = _symbol(repository_id, "abc", "app.service.run")
        await code_graph_repository.save_symbols([symbol])
        found = await code_graph_repository.find_symbol(repository_id, "abc", "app.service.run")
        assert [s.identity_key for s in found] == [symbol.identity_key]

    async def test_relation_round_trip(self, code_graph_repository: CodeGraphRepository) -> None:
        repository_id = _repository_id()
        caller = _symbol(repository_id, "abc", "app.router.handle")
        callee = _symbol(repository_id, "abc", "app.service.run")
        await code_graph_repository.save_symbols([caller, callee])
        relation = CodeRelation(
            relation_type=CodeRelationType.CALLS,
            source_identity=caller.identity,
            target_identity=callee.identity,
            repository_id=repository_id,
            revision="abc",
            source_path=caller.path,
            target_path=callee.path,
        )
        await code_graph_repository.save_relations([relation])
        relations = await code_graph_repository.list_relations(repository_id, "abc")
        assert len(relations) == 1
        assert relations[0].relation_type == CodeRelationType.CALLS
        assert relations[0].target_identity.qualified_name == "app.service.run"

    async def test_save_parsed_file(self, code_graph_repository: CodeGraphRepository) -> None:
        repository_id = _repository_id()
        parsed = ParsedFile(
            path="app/service.py",
            module="app.service",
            language="python",
            repository_id=repository_id,
            revision="abc",
            content_hash="abc123",
            symbols=[_symbol(repository_id, "abc", "app.service.run")],
        )
        await code_graph_repository.save_parsed_file(parsed)
        symbols = await code_graph_repository.list_symbols(repository_id, "abc")
        assert len(symbols) == 1

    async def test_expire_revision(self, code_graph_repository: CodeGraphRepository) -> None:
        repository_id = _repository_id()
        await code_graph_repository.save_symbols([_symbol(repository_id, "abc", "app.service.run")])
        await code_graph_repository.expire_revision(repository_id, "abc")
        assert await code_graph_repository.list_symbols(repository_id, "abc") == []
        assert await code_graph_repository.list_relations(repository_id, "abc") == []
