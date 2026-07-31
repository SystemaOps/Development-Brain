# Phase 1 Foundation Results

Baseline date: 2026-07-20

## Scope Completed

- Split `agent_core.config` from a single module into a package.
- Preserved existing imports through `agent_core.config.__init__`.
- Added README-compatible settings aliases for current and target environment variable names.
- Added basic logging and agent definition configuration modules.
- Added vendor-free domain modules for enums, identifiers, projects, requirements, plans, tasks, feedback, evidence, verification, and events.
- Re-exported existing enum imports through `agent_core.enums`.
- Added technology-independent port protocols for LLM generation, OpenProject, event inbox, project repository, repository access, command runner, graph store, vector store, artifact store, and unit of work.
- Added a SQLAlchemy unit-of-work implementation.
- Added Alembic scaffolding under `agent_core/alembic`.
- Added baseline migration `0001_current_baseline` for the current planning schema plus webhook/job/context snapshot tables.
- Added Phase 1 tests for settings aliases and domain/port vendor-boundary enforcement.

## Runtime Compatibility Notes

- Existing `from agent_core.config import settings` imports continue to work.
- Existing `from agent_core.enums import ...` imports continue to work.
- `agent_core.workflow.__init__` was fixed because it contained invalid stray text.
- `agent_core.workflow.routing.route_after_skill` was added because `workflow.graph` already imported it.
- Planning-core startup still calls `create_schema()`; replacing that with Alembic-managed startup is intentionally left for a later migration step after database verification.

## Verification

Temporary verification environment:

```text
%TEMP%\ada-codex-phase0-venv-py311
```

Command:

```powershell
%TEMP%\ada-codex-phase0-venv-py311\Scripts\python.exe -m pytest -q
```

Result:

```text
6 passed, 3 warnings in 0.78s
```

Warnings:

- `test_ada.py::test_imports` returns `bool` instead of using assertions.
- `test_ada.py::test_agent_functionality` returns `bool` instead of using assertions.
- `test_ada.py::test_config` returns `bool` instead of using assertions.

Alembic history sanity check:

```powershell
cd agent_core
%TEMP%\ada-codex-phase0-venv-py311\Scripts\python.exe -m alembic -c alembic.ini history
```

Result:

```text
<base> -> 0001_current_baseline (head), current baseline schema
```

## Remaining Phase 1 Work

- Run the baseline migration against a clean PostgreSQL database.
- Compare Alembic-created schema with `Base.metadata` and `infra/postgres/init/01-agent-schema.sql`.
- Add repository classes behind the new ports.
- Move webhook inbox persistence behind the new `EventInboxPort`.
- Replace application startup `create_schema()` with documented migration execution after schema parity is confirmed.
- Add artifact storage implementation behind `ArtifactStorePort`.
