# Agent Platform Background Worker Results

## Summary

Durable agent flows can now be queued for background execution. PostgreSQL is both the flow
aggregate store and the work queue, so queue state, execution leases, recovery history, and final
results remain in one transactional record.

The existing synchronous endpoint remains available. The existing Redis-backed OpenProject event
worker also remains in place and has a different responsibility: it consumes webhook event IDs and
delegates event handling to the planning core.

## API

```text
POST /v1/agents/flows        reserve and execute synchronously
POST /v1/agents/flows/async  persist a queued flow and return HTTP 202
GET  /v1/agents/flows/{flow_id}
GET  /v1/agents/flows/by-workflow
```

`POST /v1/agents/flows/async` accepts the existing `AgentFlowStartPayload`. Its `max_steps` value is
stored in `execution_options` so a worker restart does not change the execution boundary. A queued
response has:

- `status: queued`
- `version: 1`
- no lease
- the serialized typed execution request as pending input

## Worker Lifecycle

`agent_core.workers.agent_flow_worker.AgentFlowWorker`:

1. Opens a short PostgreSQL session and claims one queued or recoverable row.
2. Uses oldest-first `SELECT ... FOR UPDATE SKIP LOCKED` so concurrent workers claim different
   rows without starving expired work.
3. Transitions `queued` to `running`, increments the aggregate version, and creates a lease.
4. Decodes the persisted request with a registry-backed `AgentExecutionRequestCodec`.
5. Executes the flow through `AgentPlatformService` in a separate database session.
6. Renews the lease from independent short-lived heartbeat sessions.
7. Commits the result with the original claim version and lease token.

The execution session and heartbeat sessions are intentionally independent. A long-running agent
operation cannot block its own lease renewal through concurrent use of one SQLAlchemy
`AsyncSession`.

If heartbeat persistence fails, the worker cancels the local execution. The running aggregate and
pending request remain durable. Another worker can recover it after lease expiry.

## Recovery Policy

Automatic recovery is controlled by:

```json
{
  "flow_runtime": {
    "lease_seconds": 300,
    "heartbeat_seconds": 60,
    "worker_poll_seconds": 2,
    "recovery_enabled": true,
    "max_recovery_attempts": 3
  }
}
```

`heartbeat_seconds` must be lower than `lease_seconds`. If recovery is disabled, the worker claims
only queued rows. If an expired flow reaches `max_recovery_attempts`, it transitions to
`escalated`, clears its lease, and retains the pending execution payload for diagnosis or a typed
manual resume.

Set `AGENT_PLATFORM_CONFIG_FILE` to a JSON configuration path to activate non-default runtime
values. The API, event orchestrator, and flow worker use the same loader.

Manual recovery through `POST /v1/agents/flows/{flow_id}/recover` remains available and continues
to require an exact typed request match.

## Persistence

Migration `0014_queued_agent_flows` adds `queued` to the
`agent_platform_flows.status` constraint and adds a `(status, updated_at)` claim index. No second
queue table or Redis message is required.

On downgrade, queued rows are converted to `escalated` and their JSON aggregate status and reason
are updated before the old status constraint is restored.

## Deployment

Compose includes a dedicated service:

```text
agent-flow-worker
```

It runs:

```text
python -m agent_core.workers.agent_flow_worker
```

`WORKER_CONCURRENCY` controls local worker slots and `FLOW_WORKER_ID` identifies lease ownership.
The worker uses the same database and infrastructure adapter configuration as
`planning-agent-core`.

Deploy migration `0014_queued_agent_flows` before starting the worker or accepting asynchronous
flow requests.

## Validation

Coverage includes:

- Queue creation without eager agent execution.
- Typed request decoding and codec registration failures.
- Claim, heartbeat, completion, and heartbeat-failure cancellation.
- Independent database session use for claim, execution, and heartbeat.
- Disabled recovery and exhausted-recovery escalation.
- HTTP asynchronous enqueue request construction.
- Concurrent PostgreSQL workers claiming distinct rows.
- Migration-head and Compose configuration validation.

Commands run:

```powershell
.venv/Scripts/python.exe -m ruff check <changed Python files>
.venv/Scripts/python.exe -m pytest -q tests/test_agent_flow_persistence.py tests/test_agent_flow_worker.py tests/test_agent_platform_api.py tests/test_import_smoke.py
.venv/Scripts/python.exe -m pytest -q tests/test_phase3_postgres_integration.py tests/test_agent_flow_postgres_integration.py
.venv/Scripts/python.exe -m pytest -q
docker compose config --quiet
```

Results:

- Changed-file Ruff: passed.
- Focused worker, flow, API, and import tests: 35 passed.
- Live PostgreSQL migration and flow tests: 11 passed.
- Alembic downgrade and upgrade: passed.
- Alembic head: `0014_queued_agent_flows`.
- Full suite with PostgreSQL integrations enabled: 194 passed, 2 skipped, 4 existing warnings.
