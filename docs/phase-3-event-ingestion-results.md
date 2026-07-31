# Phase 3 Event Ingestion Results

Baseline date: 2026-07-21

## Scope Completed

- Added typed event processing and job statuses to the domain event layer.
- Added deterministic event idempotency key generation based on canonical event fields and payload.
- Added core OpenProject event normalization under `agent_core.application.event_classification`.
- Added SQLAlchemy ORM models for the existing webhook tables: `pm_webhook_events`, `agent_jobs`, and `pm_context_snapshots`.
- Added `idempotency_key` and `retry_at` to `pm_webhook_events`.
- Added job lease, retry, attempt-count, and terminal error fields to `agent_jobs`: `attempt_count`, `retry_at`, `lease_owner`, `lease_expires_at`, and `last_error`.
- Added README-aligned `agent_executions` workflow execution tracking table.
- Added Alembic migration `0002_webhook_event_idempotency`.
- Added Alembic migration `0003_agent_job_leases`.
- Added Alembic migration `0004_agent_executions`.
- Added async `SqlAlchemyEventInbox` adapter with PostgreSQL `ON CONFLICT DO NOTHING` duplicate handling.
- Added `AgentExecutionRecorderPort` and `SqlAlchemyAgentExecutionRecorder`.
- Changed the event inbox port to return `EventInboxPersistResult` with `created` status so callers can avoid enqueueing duplicate deliveries.
- Added event queue port and Redis queue adapter.
- Added deterministic retry classification helper in the core package.
- Added shared bounded retry-delay helper in the core package.
- Migrated `infra/agent_trigger` webhook parsing to compute the same idempotency key as the core event classifier.
- Migrated `infra/agent_trigger` storage to persist duplicate-safe webhook events with `ON CONFLICT (idempotency_key) DO NOTHING`.
- Updated `infra/agent_trigger` webhook response behavior so duplicate deliveries return `status: duplicate` and do not enqueue another Redis item.
- Replaced trigger-local parser and retry-policy implementations with thin wrappers around shared `agent_core` code.
- Changed `agent-webhook` and `agent-worker` Docker build context so the trigger image copies the shared core package.
- Added trigger worker lease acquisition before event processing.
- Added bounded retry scheduling with durable `retry_at` and recoverable job re-enqueue scanning.
- Added terminal `dead_letter` recording for non-retryable failures or exhausted attempts.
- Added `ProjectEventOrchestrator` to load persisted inbox events, resolve local project mappings, and route resumable OpenProject feedback into the planning workflow runner.
- Updated `ProjectEventOrchestrator` to record planning workflow executions and finish them as `succeeded`, `waiting`, or `failed`.
- Added `POST /v1/events/{event_id}/orchestrate` as a manual core entry point for persisted-event orchestration.
- Added a trigger-side core orchestration client for `POST /v1/events/{event_id}/orchestrate`.
- Narrowed `infra/agent_trigger` worker behavior to queue lease, retry, dead-letter, and core orchestration delegation.
- Updated `agent-worker` Compose configuration to depend on `planning-agent-core` and use `PLANNING_AGENT_CORE_URL`.
- Added explicit LangGraph persistence setup command at `infra/scripts/setup_langgraph_persistence.py`.
- Added reusable `initialize_langgraph_persistence()` helper for `AsyncPostgresSaver.setup()` and `AsyncPostgresStore.setup()`.
- Added `make setup-langgraph` shortcut for the dedicated persistence setup command.
- Updated the Docker-init PostgreSQL schema to match the new idempotency, lease, retry, and dead-letter columns.
- Added tests for event fingerprints, OpenProject normalization, ORM table registration, PostgreSQL conflict SQL, Redis queue behavior, retry classification, trigger/core shared parser and retry wrappers, trigger duplicate handling, worker lease SQL, core orchestration delegation, retry scheduling, dead-letter recording, recoverable job scanning, persisted-event orchestrator routing, execution recording, LangGraph persistence setup wiring, and stable checkpoint resume config.
- Added an opt-in real-Postgres LangGraph restart test guarded by `LANGGRAPH_PERSISTENCE_TEST_DATABASE_URL`.
- Added opt-in real-Postgres migration and duplicate webhook tests guarded by `PHASE3_POSTGRES_DATABASE_URL`.
- Installed `redis>=5.2` into the repaired `.venv`.

## Runtime Compatibility Notes

- `infra/agent_trigger` remains a standalone service, but its Docker image now copies the shared core package for parser and retry-policy imports.
- Update 2026-07-23: `ProjectEventOrchestrator` can now route resumable planning events through `AgentPlatformService` when configured; the original `PlanningWorkflowRunner` path remains a fallback for compatibility.
- The live trigger worker still uses synchronous `psycopg` only for queue lease and compatibility job bookkeeping.
- Duplicate delivery safety is now enforced in both the core inbox adapter and the live trigger storage path.
- Worker lease and retry behavior is now durable in `agent_jobs`.
- `agent_jobs` remains as the trigger service queue compatibility table; core workflow execution history is captured separately in `agent_executions`.
- The core orchestrator resumes planning with the existing `planning-session-{session_id}` LangGraph thread ID, so checkpoint resume can work once a durable checkpointer is configured.
- The LangGraph setup script loads `.env` by default and redacts credentials in output.
- The setup script normalizes `postgresql+asyncpg://` to `postgresql://`, matching the driver expected by LangGraph's Postgres checkpointer.
- The planning workflow now uses the stable `planning-session-{session_id}` LangGraph `thread_id` without a top-level `checkpoint_ns`; current LangGraph treats that namespace as a subgraph lookup during state restoration.
- OpenProject event-to-project resolution currently depends on `ExternalArtifact` mappings for `project` or `work_package` artifacts.
- Feedback classification is intentionally coarse in this slice; detailed requirement-change, approval, pause, resume, and cancellation semantics remain Phase 4 work.
- `create_schema()` remains in planning-core startup, so Alembic is scaffolded but not yet enforced at service startup.

## Verification

Environment:

```text
C:\repo_gitlab\Ada\.venv
```

Command:

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -m pytest -q
```

Result:

```text
50 passed, 3 skipped, 4 warnings in 1.08s
```

Skipped:

- `tests/test_phase3_langgraph_persistence.py::test_langgraph_postgres_checkpoint_survives_recreated_checkpointer` requires `LANGGRAPH_PERSISTENCE_TEST_DATABASE_URL`.
- `tests/test_phase3_postgres_integration.py::test_phase3_alembic_upgrade_creates_expected_tables` requires `PHASE3_POSTGRES_DATABASE_URL`.
- `tests/test_phase3_postgres_integration.py::test_phase3_event_inbox_duplicate_delivery_creates_one_job` requires `PHASE3_POSTGRES_DATABASE_URL`.

Warnings:

- `fastapi.testclient` emits a Starlette deprecation warning about `httpx`.
- `test_ada.py::test_imports` returns `bool` instead of using assertions.
- `test_ada.py::test_agent_functionality` returns `bool` instead of using assertions.
- `test_ada.py::test_config` returns `bool` instead of using assertions.

Compose validation:

```powershell
docker compose config --quiet
```

Result:

```text
passed
```

Alembic history sanity check:

```powershell
cd agent_core
..\.venv\Scripts\python.exe -m alembic -c alembic.ini history
```

Result:

```text
0003_agent_job_leases -> 0004_agent_executions (head), add agent execution tracking
0002_webhook_event_idempotency -> 0003_agent_job_leases, add agent job leases and retry scheduling
0001_current_baseline -> 0002_webhook_event_idempotency, add webhook event idempotency key
<base> -> 0001_current_baseline, current baseline schema
```

## Remaining Phase 3 Work

- Remove the legacy trigger OpenProject client and agent placeholder after Phase 4 replaces them with the unified OpenProject adapter and coding workflow.
- Add visible OpenProject dead-letter comments once outbound OpenProject writes have idempotency markers.

## Live PostgreSQL Verification

Docker engine:

```text
29.1.3
```

Command:

```powershell
$name = "ada-phase3-pg-$PID"
docker run --rm -d --name $name -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=ada_phase3 -p 127.0.0.1::5432 postgres:17-alpine
$env:PHASE3_POSTGRES_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:<port>/ada_phase3"
$env:LANGGRAPH_PERSISTENCE_TEST_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:<port>/ada_phase3"
.venv\Scripts\python.exe -m pytest -q tests/test_phase3_postgres_integration.py tests/test_phase3_langgraph_persistence.py::test_langgraph_postgres_checkpoint_survives_recreated_checkpointer
docker rm -f $name
```

Result:

```text
3 passed in 2.82s
```

Issues found and fixed during the live run:

- On Windows, psycopg async cannot run on the default proactor event loop; `tests/conftest.py` now sets `WindowsSelectorEventLoopPolicy` for pytest on Windows.
- `checkpoint_ns="planning"` caused LangGraph state restoration to look for a subgraph named `planning`; `PlanningWorkflowRunner` now relies on the stable `thread_id` only.
