# Agent Platform API Integration Results

## Summary

Added application API entry points for one-step execution and durable flow operation through the
orchestrator. The routes preserve the existing FastAPI application style and use typed request
models at the HTTP boundary.

## Implemented

- Added `agent_core/api/agents.py` with `POST /v1/agents/execute`.
- Registered the agents router in `agent_core/main.py`.
- Added `AgentExecutePayload` with a discriminated union over `PlanningAgentRequest`, `CodingAgentRequest`, and `VerificationAgentRequest`.
- Added `AgentExecutionResponse` containing the persisted result ID, typed agent result, and route decision.
- The endpoint loads default agent configuration when no explicit config is supplied.
- The endpoint rejects mismatched `config.agent_type` and `request.agent_type`.
- The endpoint builds `AgentPlatformService` with request-scoped SQLAlchemy-backed checkpoint and result stores.
- Request/result models now use literal agent types for strong API discrimination.
- Agent validation wraps Pydantic validation failures in `AgentValidationError` to preserve the platform error contract.
- Added durable flow start, lookup, approval/resume, workflow discovery, heartbeat, and expired-run
  recovery routes.
- Flow version and lease conflicts map to HTTP `409`.
- Recovery reuses persisted workflow, correlation, and configuration identity and requires the
  original typed request.
- Added a typed Verification override endpoint that enforces persisted policy and optimistic
  versioning while retaining the original failed result.

## Endpoint

```http
POST /v1/agents/execute
POST /v1/agents/flows
GET  /v1/agents/flows/by-workflow
GET  /v1/agents/flows/{flow_id}
POST /v1/agents/flows/{flow_id}/heartbeat
POST /v1/agents/flows/{flow_id}/recover
POST /v1/agents/flows/{flow_id}/resume
POST /v1/agents/flows/{flow_id}/verification-override
```

Example planning payload:

```json
{
  "request": {
    "agent_type": "planning",
    "project_id": "demo",
    "objective": "Create an implementation plan for the agent platform"
  },
  "workflow_id": "workflow-demo",
  "correlation_id": "request-123"
}
```

Example response shape:

```json
{
  "persisted_result_id": "00000000-0000-0000-0000-000000000000",
  "result": {
    "execution_id": "00000000-0000-0000-0000-000000000000",
    "project_id": "demo",
    "agent_type": "planning",
    "status": "waiting",
    "summary": "Requirements were extracted, but no plan was provided or generated.",
    "next_action": "request_clarification"
  },
  "route": {
    "next_agent_type": null,
    "requires_approval": false,
    "escalate": true,
    "reason": "Agent requested explicit next action."
  }
}
```

## Validation

Commands run:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_agent_platform_api.py tests/test_agent_platform.py tests/test_import_smoke.py
.venv/Scripts/python.exe -m ruff check agent_core/agent_core/api/agents.py agent_core/agent_core/main.py agent_core/agent_core/agent_platform agent_core/agent_core/services/agent_platform_service.py agent_core/agent_core/persistence/agent_platform.py tests/test_agent_platform_api.py tests/test_agent_platform.py tests/test_import_smoke.py
.venv/Scripts/python.exe -m pytest -q
```

Results:

- Focused flow, API, and platform tests: 47 passed.
- Ruff: passed.
- Full test suite with PostgreSQL integrations enabled: 183 passed, 2 skipped, 4 existing
  warnings.

## Remaining Follow-Up

- Add authenticated/authorized production usage once user-management or gateway policy exists outside this project.
- Add production composition for external adapters such as Neo4j, Weaviate, OpenProject, repository filesystem, and command runner secrets.
