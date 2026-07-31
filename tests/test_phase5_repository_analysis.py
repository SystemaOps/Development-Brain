from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_core.domain.code_analysis import (
    CodeRelationship,
    CodeRelationshipKind,
    CodeSymbol,
    CodeSymbolKind,
    RepositoryIndex,
    SyntaxExtractionResult,
)
from agent_core.domain.enums import RepositoryAccessMode
from agent_core.domain.repositories import (
    RepositoryAccessDenied,
    RepositoryBinding,
    RepositoryPathError,
    assert_command_allowed,
    normalize_repository_relative_path,
    path_matches_any,
    resolve_repository_path,
)


def test_repository_binding_defaults_are_read_only_and_protect_sensitive_paths(tmp_path: Path):
    binding = RepositoryBinding(repository_key="demo-repo", mount_path=str(tmp_path))

    assert binding.access_mode == RepositoryAccessMode.READ_ONLY
    assert ".git/**" in binding.denylist
    assert binding.write_allowlist == ()
    assert binding.command_allowlist == ()


def test_repository_relative_path_validation_rejects_escape_attempts():
    for path in [
        "../secret.txt",
        "src/../../secret.txt",
        "/etc/passwd",
        "C:/Windows/System32/config",
        "C:Windows/System32/config",
        "src/app.py\x00suffix",
    ]:
        with pytest.raises(RepositoryPathError):
            normalize_repository_relative_path(path)


def test_repository_path_policy_rejects_denylisted_reads(tmp_path: Path):
    repo = tmp_path / "repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text("secret", encoding="utf-8")
    binding = RepositoryBinding(repository_key="demo-repo", mount_path=str(repo))

    with pytest.raises(RepositoryAccessDenied, match="denied"):
        resolve_repository_path(binding, ".git/config")


def test_repository_path_policy_rejects_symlink_escape(tmp_path: Path):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    link = repo / "linked-secret.txt"
    try:
        link.symlink_to(outside_file)
    except OSError as exc:
        pytest.skip(f"Symlink creation is not available in this environment: {exc}")

    binding = RepositoryBinding(repository_key="demo-repo", mount_path=str(repo))

    with pytest.raises(RepositoryPathError, match="escapes"):
        resolve_repository_path(binding, "linked-secret.txt")


def test_repository_write_policy_requires_read_write_mode_and_allowlist(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("demo", encoding="utf-8")

    read_only = RepositoryBinding(repository_key="demo-repo", mount_path=str(repo))
    with pytest.raises(RepositoryAccessDenied, match="not writable"):
        resolve_repository_path(read_only, "README.md", for_write=True)

    no_allowlist = RepositoryBinding(
        repository_key="demo-repo",
        mount_path=str(repo),
        access_mode=RepositoryAccessMode.READ_WRITE,
    )
    with pytest.raises(RepositoryAccessDenied, match="no write allowlist"):
        resolve_repository_path(no_allowlist, "README.md", for_write=True)

    allowlisted = RepositoryBinding(
        repository_key="demo-repo",
        mount_path=str(repo),
        access_mode=RepositoryAccessMode.READ_WRITE,
        write_allowlist=("src/**",),
    )
    (repo / "src").mkdir()
    resolved = resolve_repository_path(allowlisted, "src/new_file.py", for_write=True)
    assert resolved.absolute_path == repo.resolve() / "src" / "new_file.py"

    with pytest.raises(RepositoryAccessDenied, match="outside the write allowlist"):
        resolve_repository_path(allowlisted, "README.md", for_write=True)


def test_repository_command_allowlist_uses_executable_names(tmp_path: Path):
    binding = RepositoryBinding(
        repository_key="demo-repo",
        mount_path=str(tmp_path),
        command_allowlist=("pytest",),
    )

    assert_command_allowed(binding, ["pytest", "-q"])

    with pytest.raises(RepositoryAccessDenied, match="not allowed"):
        assert_command_allowed(binding, ["python", "-m", "pytest"])

    with pytest.raises(ValidationError, match="not shell commands"):
        RepositoryBinding(
            repository_key="bad-repo",
            mount_path=str(tmp_path),
            command_allowlist=("pytest -q",),
        )


@pytest.mark.asyncio
async def test_local_repository_filesystem_reads_only_inside_binding(tmp_path: Path):
    from agent_core.adapters.repository_filesystem import LocalRepositoryFilesystem

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")
    filesystem = LocalRepositoryFilesystem(
        [RepositoryBinding(repository_key="demo-repo", mount_path=str(repo))]
    )

    assert await filesystem.read_text(
        repository_key="demo-repo",
        relative_path="README.md",
    ) == "hello"
    assert filesystem.resolve_path(
        repository_key="demo-repo",
        relative_path="./README.md",
    ) == str((repo / "README.md").resolve())

    with pytest.raises(RepositoryPathError):
        filesystem.resolve_path(repository_key="demo-repo", relative_path="../README.md")

    snapshot = await filesystem.snapshot(repository_key="demo-repo")
    assert snapshot.repository_key == "demo-repo"
    assert snapshot.commit_sha is None
    assert snapshot.status_porcelain == ""
    assert snapshot.warning
    assert await filesystem.status(repository_key="demo-repo") == ""


@pytest.mark.asyncio
async def test_python_ast_repository_analyzer_indexes_sample_project():
    from agent_core.adapters.repository_analysis import PythonAstRepositoryAnalyzer

    repo_root = Path(__file__).resolve().parents[1]
    sample_project = repo_root / "sample_project"
    binding = RepositoryBinding(
        repository_key="sample-project",
        mount_path=str(sample_project),
    )

    index = await PythonAstRepositoryAnalyzer([binding]).index_repository(
        repository_key="sample-project"
    )

    symbols_by_name = {(symbol.kind, symbol.name): symbol for symbol in index.symbols}
    assert (CodeSymbolKind.FILE, "main.py") in symbols_by_name
    assert (CodeSymbolKind.FUNCTION, "calculate_total") in symbols_by_name
    assert (CodeSymbolKind.FUNCTION, "checkout") in symbols_by_name
    assert (CodeSymbolKind.IMPORT, "services.payment.PaymentService") in symbols_by_name

    checkout = symbols_by_name[(CodeSymbolKind.FUNCTION, "checkout")]
    calculate_total = symbols_by_name[(CodeSymbolKind.FUNCTION, "calculate_total")]
    assert any(
        relationship.relationship_type == CodeRelationshipKind.CALLS
        and relationship.source_symbol_key == checkout.symbol_key
        and relationship.target_symbol_key == calculate_total.symbol_key
        for relationship in index.relationships
    )
    assert any(
        relationship.relationship_type == CodeRelationshipKind.UNRESOLVED_CALL
        and relationship.source_symbol_key == checkout.symbol_key
        and relationship.target_name == "PaymentService"
        for relationship in index.relationships
    )
    assert any("LSP analysis is unavailable" in warning for warning in index.warnings)


def test_tree_sitter_extractor_reports_unavailable_without_hard_dependency(tmp_path: Path):
    from agent_core.adapters.tree_sitter_analysis import TreeSitterPythonExtractor

    path = tmp_path / "main.py"
    path.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    result = TreeSitterPythonExtractor(enabled=False).extract_python_file(
        repository_key="demo-repo",
        relative_path="main.py",
        absolute_path=path,
    )

    assert result.available is False
    assert result.source == "tree_sitter_python"
    assert "disabled" in result.warnings[0]


@pytest.mark.asyncio
async def test_lsp_lookup_reports_unavailable_without_starting_server(tmp_path: Path):
    from agent_core.adapters.lsp import LegacyPythonLspLookup

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    binding = RepositoryBinding(repository_key="demo-repo", mount_path=str(repo))

    lookup = LegacyPythonLspLookup(binding=binding, enabled=False)

    assert lookup.is_available() is False
    result = await lookup.definition(
        repository_key="demo-repo",
        relative_path="main.py",
        line=0,
        character=4,
    )
    assert result.available is False
    assert "LSP lookup is unavailable" in result.warnings[0]


@pytest.mark.asyncio
async def test_python_ast_analyzer_records_tree_sitter_metadata_from_extractor(tmp_path: Path):
    from agent_core.adapters.repository_analysis import PythonAstRepositoryAnalyzer

    class FakeTreeSitterExtractor:
        def extract_python_file(self, *, repository_key, relative_path, absolute_path):
            return SyntaxExtractionResult(
                available=True,
                source="fake_tree_sitter",
                relative_path=relative_path,
                functions=({"name": "hello"},),
                calls=({"callee_text": "hello"},),
            )

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    binding = RepositoryBinding(repository_key="demo-repo", mount_path=str(repo))

    index = await PythonAstRepositoryAnalyzer(
        [binding],
        syntax_extractor=FakeTreeSitterExtractor(),
    ).index_repository(repository_key="demo-repo")

    file_symbol = next(symbol for symbol in index.symbols if symbol.kind == CodeSymbolKind.FILE)
    assert file_symbol.metadata["syntax_source"] == "fake_tree_sitter"
    assert file_symbol.metadata["tree_sitter_function_count"] == 1
    assert file_symbol.metadata["tree_sitter_call_count"] == 1


@pytest.mark.asyncio
async def test_repository_projectors_write_to_graph_and_vector_ports():
    from uuid import uuid4

    from agent_core.services.repository_projection_service import (
        REPOSITORY_CONTEXT_COLLECTION,
        RepositoryNeo4jProjector,
        RepositoryVectorProjector,
    )

    project_id = uuid4()
    file_symbol = CodeSymbol(
        symbol_key="sample-project:file:main.py:main.py:1",
        repository_key="sample-project",
        relative_path="main.py",
        name="main.py",
        kind=CodeSymbolKind.FILE,
        language="python",
    )
    function_symbol = CodeSymbol(
        symbol_key="sample-project:function:main.py:checkout:13",
        repository_key="sample-project",
        relative_path="main.py",
        name="checkout",
        kind=CodeSymbolKind.FUNCTION,
        language="python",
        start_line=13,
        metadata={"qualname": "checkout"},
    )
    index = RepositoryIndex(
        repository_key="sample-project",
        symbols=(file_symbol, function_symbol),
        relationships=(
            CodeRelationship(
                repository_key="sample-project",
                source_symbol_key=file_symbol.symbol_key,
                target_symbol_key=function_symbol.symbol_key,
                target_name="checkout",
                relationship_type=CodeRelationshipKind.DEFINES,
            ),
        ),
    )

    class FakeGraphStore:
        def __init__(self):
            self.nodes = []
            self.relations = []

        async def ensure_schema(self):
            self.schema_ensured = True

        async def upsert_node(self, **kwargs):
            self.nodes.append(kwargs)

        async def upsert_relation(self, **kwargs):
            self.relations.append(kwargs)

    class FakeVectorStore:
        def __init__(self):
            self.upserts = []
            self.searches = []

        async def ensure_schema(self):
            self.schema_ensured = True

        async def upsert_text(self, **kwargs):
            self.upserts.append(kwargs)

        async def search(self, **kwargs):
            self.searches.append(kwargs)
            return [{"id": "result-1", "properties": {"name": "checkout"}}]

    graph = FakeGraphStore()
    vector = FakeVectorStore()

    graph_mutations = await RepositoryNeo4jProjector(graph).project_index(
        project_id=project_id,
        index=index,
    )
    vector_upserts = await RepositoryVectorProjector(vector).upsert_repository_context(
        project_id=project_id,
        index=index,
    )
    search_results = await RepositoryVectorProjector(vector).search_repository_context(
        query="checkout",
        limit=5,
    )

    assert graph_mutations == 6
    assert any(node["labels"] == ("Repository",) for node in graph.nodes)
    assert any(
        relation["relation_type"] == CodeRelationshipKind.DEFINES.value.upper()
        for relation in graph.relations
    )
    assert vector_upserts == 2
    assert vector.upserts[0]["collection"] == REPOSITORY_CONTEXT_COLLECTION
    assert search_results[0]["properties"]["name"] == "checkout"


def test_repository_api_router_exposes_binding_index_and_query_routes():
    from agent_core.api.repositories import router

    paths = {route.path for route in router.routes}

    assert "/v1/projects/{project_key}/repositories" in paths
    assert "/v1/projects/{project_key}/repositories/{repository_key}/index" in paths
    assert "/v1/projects/{project_key}/repositories/{repository_key}/snapshot" in paths
    assert "/v1/projects/{project_key}/repositories/{repository_key}/symbols" in paths
    assert "/v1/projects/{project_key}/repositories/{repository_key}/relationships" in paths
    assert "/v1/projects/{project_key}/repositories/{repository_key}/search" in paths


def test_repository_projection_adapters_match_async_ports():
    from agent_core.adapters.neo4j_store import Neo4jProjectionStore
    from agent_core.adapters.weaviate_store import WeaviateSchemaStore

    assert inspect.iscoroutinefunction(Neo4jProjectionStore.ensure_schema)
    assert inspect.iscoroutinefunction(Neo4jProjectionStore.upsert_node)
    assert inspect.iscoroutinefunction(Neo4jProjectionStore.upsert_relation)
    assert inspect.iscoroutinefunction(WeaviateSchemaStore.ensure_schema)
    assert inspect.iscoroutinefunction(WeaviateSchemaStore.upsert_text)
    assert inspect.iscoroutinefunction(WeaviateSchemaStore.search)


def test_repository_binding_model_and_migration_contract():
    from agent_core.models import (
        RepositoryBindingRecord,
        RepositoryRelationshipRecord,
        RepositorySymbolRecord,
    )

    assert RepositoryBindingRecord.__tablename__ == "repository_bindings"
    binding_columns = RepositoryBindingRecord.__table__.columns
    assert {
        "project_id",
        "repository_key",
        "mount_path",
        "access_mode",
        "write_allowlist",
        "denylist",
        "command_allowlist",
        "binding_metadata",
    } <= set(binding_columns.keys())
    assert any(
        constraint.name == "uq_repository_bindings_project_key"
        for constraint in RepositoryBindingRecord.__table__.constraints
    )
    assert RepositorySymbolRecord.__tablename__ == "repository_symbols"
    assert {
        "project_id",
        "repository_key",
        "symbol_key",
        "relative_path",
        "name",
        "kind",
        "language",
        "symbol_metadata",
    } <= set(RepositorySymbolRecord.__table__.columns.keys())
    assert RepositoryRelationshipRecord.__tablename__ == "repository_relationships"
    assert {
        "project_id",
        "repository_key",
        "source_symbol_key",
        "target_symbol_key",
        "target_name",
        "relationship_type",
        "relationship_metadata",
    } <= set(RepositoryRelationshipRecord.__table__.columns.keys())


def test_repository_path_pattern_matching_is_repo_relative():
    assert path_matches_any("src/app.py", ("src/**",))
    assert path_matches_any("src", ("src/**",))
    assert path_matches_any("nested/.git/config", ("**/.git/**",))
    assert not path_matches_any("README.md", ("src/**",))

    with pytest.raises(ValueError, match="must be relative"):
        RepositoryBinding(
            repository_key="bad-repo",
            mount_path="repo",
            write_allowlist=("/tmp/**",),
        )
