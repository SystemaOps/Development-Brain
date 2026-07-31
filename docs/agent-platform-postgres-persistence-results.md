# Agent Platform PostgreSQL Persistence Results

## Summary

Added PostgreSQL-backed persistence for agent-platform checkpoints, result payloads, and aggregate
flows. This keeps agent state and cross-agent outputs durable without coupling platform execution
to the existing `agent_executions` metadata table or requiring a project UUID foreign key.

## Implemented

- `agent_platform_checkpoints` table for agent-scoped checkpoint state.
- `agent_platform_results` table for typed agent result payloads.
- `agent_platform_flows` table for versioned flow status, step history, approvals, and pending
  execution recovery data.
- Alembic migration `0011_agent_platform_persistence`.
- Alembic migration `0012_agent_platform_flows`.
- Alembic migration `0013_agent_flow_recovery_leases`.
- SQLAlchemy checkpoint store implementing the platform `CheckpointStore` protocol.
- SQLAlchemy result store implementing the platform `AgentResultStore` protocol.
- Common `AgentResult` now carries typed `project_id` and `task_id` fields for durable indexing.
- Planning, Coding, Verification, and orchestrator failure results populate `project_id` and `task_id`.
- `AgentOrchestrator` uses `dependencies.result_store` when no explicit result store is passed.
- Local contract tests for persistence model registration and dependency-injected result storage.
- Live Postgres integration coverage for checkpoint upsert/load and result persistence.
- Live Postgres integration coverage for flow reservation, approval resume, append-only history,
  optimistic version conflicts, and indexed aggregate state.
- Live Postgres integration coverage for heartbeat, expired-lease recovery, recovery history,
  relational lease cleanup, and workflow lookup.

## Tables

`agent_platform_checkpoints` identity columns:

- `project_key`
- `workflow_id`
- `agent_type`
- `agent_instance_id`
- `execution_id`
- `thread_id`
- `checkpoint_id`

`agent_platform_results` indexing columns:

- `execution_id`
- `project_key`
- `task_key`
- `agent_type`
- `status`
- `next_action`

`agent_platform_flows` indexing columns:

- `workflow_id`
- `project_key`
- `task_key`
- `status`
- `version`
- `current_agent_type`
- `current_execution_id`
- `pending_action`
- `pending_agent_type`
- `requires_approval`
- `correlation_id`
- `resume_count`
- `recovery_count`
- `lease_id`
- `lease_owner`
- `lease_acquired_at`
- `lease_expires_at`
- `last_approval_decision`

## Validation

Commands run:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_agent_flow_postgres_integration.py tests/test_phase3_postgres_integration.py::test_phase3_alembic_upgrade_creates_expected_tables
.venv/Scripts/python.exe -m ruff check agent_core/agent_core/agent_platform agent_core/agent_core/persistence/agent_platform.py agent_core/agent_core/persistence/agent_flows.py agent_core/agent_core/services/agent_platform_service.py
..\\.venv\\Scripts\\python.exe -m alembic -c alembic.ini heads
.venv/Scripts/python.exe -m pytest -q
```

Results:

- Flow store and migration focused tests against live PostgreSQL: 2 passed.
- Ruff: passed.
- Alembic heads: `0013_agent_flow_recovery_leases (head)`.
- Full test suite with PostgreSQL integrations enabled: 183 passed, 2 skipped, 4 existing
  warnings.

Live Postgres validation remains behind `PHASE3_POSTGRES_DATABASE_URL`, consistent with the existing integration test strategy.
