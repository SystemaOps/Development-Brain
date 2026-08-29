# Runtime Composition Audit (Phase 21.1)

Audit of existing construction logic in the Brain library, performed before
building the runtime composition root.  Goal: understand current wiring,
identify duplicate construction paths, and decide what the new runtime
composition must reuse.

## 1. Existing Construction Helpers

### 1.1 PostgreSQL (state layer)

- `brain/adapters/postgresql/config.py`
  - `DatabaseSettings` — frozen `dataclass`, reads `BRAIN_DATABASE_URL`,
    `BRAIN_DATABASE_ECHO`, `BRAIN_DATABASE_POOL_SIZE`,
    `BRAIN_DATABASE_MAX_OVERFLOW` from env in `from_env()`.
  - Used by Alembic (`env.py`) and tests via `DatabaseSettings()`.
- `brain/adapters/postgresql/database.py`
  - `create_async_engine(settings: DatabaseSettings) -> AsyncEngine`
  - `async_session_factory(engine) -> async_sessionmaker`
  - `PostgresRepositories` — session-bound bundle of every state repository
    (projects, repositories, actors, work_items, requirements, documents,
    executions, decisions, evidence, artifacts, verification_results,
    verification_runs, work_management_integrations, workflow_checkpoints,
    approvals, metrics, runtime_evidence, executor_quality, context_feedback,
    idempotency, event_log, repository_snapshots, repository_change_sets,
    software_catalog, code_graph, context_capsules, plans).
  - `create_repositories(session) -> PostgresRepositories`.
- `brain/adapters/postgresql/unit_of_work.py`
  - `PostgresUnitOfWork(session_factory)` — async context manager exposing
    `uow.repos` and `commit()`.

### 1.2 Neo4j (knowledge graph)

- `brain/adapters/neo4j/config.py` — `Neo4jSettings` frozen dataclass
  (`BRAIN_NEO4J_URI/USER/PASSWORD/DATABASE`), `from_env()`.
- `brain/adapters/neo4j/knowledge_graph.py` — `Neo4jKnowledgeGraph(settings)`
  constructs the driver lazily; has `close()`.

### 1.3 Weaviate (semantic index)

- `brain/adapters/weaviate/config.py` — `WeaviateSettings` frozen dataclass
  (`BRAIN_WEAVIATE_HOST/PORT/GRPC_PORT/SCHEME/CLASS_NAME`), `from_env()`.
- `brain/adapters/weaviate/semantic_index.py` — `WeaviateSemanticIndex(...)`
  with `close()`.

### 1.4 Executors (Phase 12)

- `brain/adapters/executors/fake.py` — `FakeExecutor` (in-memory, deterministic).
- `brain/adapters/executors/pi.py` — `PiExecutor` (JSONL transport, lazy).
- `brain/adapters/in_memory/executor_registry.py` — `InMemoryExecutorRegistry`
  with `register/unregister/list/get/select`.
- No executor is currently constructed by any factory; tests build the
  registry manually.

### 1.5 Verification (Phase 13)

- `brain/adapters/verification/command_runner.py` — `DeterministicCommandRunner`,
  `FakeCommandRunner`.
- `brain/adapters/verification/fake_pr.py` — `FakePullRequestAdapter`.
- `VerificationEngine` is constructed per-test with runner/results/code_graph.

### 1.6 Integrations

- `brain/adapters/work_management/openproject.py` — `OpenProjectAdapter`
  (needs an `OpenProjectTransport` protocol implementation + `ProjectId`).
- `brain/adapters/work_management/jira.py` — `JiraAdapter` (same pattern).
- `brain/adapters/documentation/git_markdown.py` — `GitMarkdownDocumentationAdapter`
  (needs a `GitMarkdownTransport`).
- `brain/adapters/documentation/xwiki.py` — `XWikiDocumentationAdapter`
  (needs an `XWikiTransport`).
- `brain/adapters/catalog/derived.py` — `DerivedCatalogPortAdapter` (default).
- `brain/adapters/catalog/backstage.py` — `BackstageCatalogAdapter` (optional).
- No transports are implemented in the library yet; adapters take protocol
  transports so tests inject fakes.  The runtime must provide HTTP transports
  or leave the capability DISABLED/UNAVAILABLE.

### 1.7 In-memory reference adapters

- `brain/adapters/in_memory/` — event bus, event log, idempotency, artifact
  store, checkpoint store, code graph, context capsules, knowledge graph,
  semantic index, verification runs, work-management integration,
  workflow checkpoints, approvals, metrics, runtime evidence, executor
  quality, context feedback, planning, repositories, catalog, executors.

## 2. Settings Loading Today

- Three adapter-local `from_env()` dataclasses (Postgres/Neo4j/Weaviate).
- Alembic uses `DatabaseSettings().url` (or `BRAIN_DATABASE_URL`).
- No central settings object; no `.env` file support; no YAML config.
- Every runtime process would otherwise re-read env vars independently.

## 3. Async Initialization Requirements

- PostgreSQL engine: created eagerly; sessions are created per-use
  (no startup I/O needed, but pool is lazy).
- Neo4j driver: constructed lazily on first query.
- Weaviate client: constructed in `__init__`.
- All three expose a `close()` (or engine.dispose) for shutdown.
- Optional providers (OpenProject/XWiki/Docling/Backstage/Pi) have no
  implemented transports — runtime construction must not require them.

## 4. Duplicate Construction Paths

- `DatabaseSettings` is instantiated in tests, Alembic, and adapter tests via
  three different entry points (direct default, `from_env()`, explicit).
  No shared runtime owner exists today.
- Repositories are rebuilt per-test via `create_repositories`; the runtime
  will own one session-bound bundle per process.
- Executor registry is created per-test; runtime must own one.

## 5. Provider-Specific Construction Leaks

- None detected: adapters accept protocol transports / settings objects and
  never read env vars deep inside business logic.
- The runtime composition root must preserve this by constructing adapters
  from resolved settings and passing ports only.

## 6. Reuse Decisions

- Reuse `create_async_engine`, `async_session_factory`, `PostgresUnitOfWork`,
  and `PostgresRepositories` unchanged.
- Reuse `Neo4jKnowledgeGraph(settings)` and `WeaviateSemanticIndex(settings)`
  as-is.
- Reuse `InMemoryExecutorRegistry`, `FakeExecutor`, `DeterministicCommandRunner`
  as the Milestone-1 defaults (Pi stays out until Milestone 2).
- Introduce a new `BrainSettings` (pydantic-settings) hierarchy that embeds
  the existing dataclass settings as the runtime configuration surface.
- Introduce a `BrainContainer` + `create_brain_container(settings)` + idempotent
  `close()` in `brain/bootstrap/`.
