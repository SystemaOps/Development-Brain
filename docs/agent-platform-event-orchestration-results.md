# Agent Platform Event Orchestration Results

## Summary

OpenProject event orchestration now routes resumable planning events through `AgentPlatformService` when configured. The existing `PlanningWorkflowRunner` path remains available as a compatibility fallback for callers and tests that do not yet provide the platform service.

## Implemented

- `ProjectEventOrchestrator` accepts an optional `agent_platform_service` dependency.
- Resumable planning events create a typed `PlanningAgentRequest` with:
  - `project_id` set to the local project key.
  - `session_id` set to the waiting planning session.
  - `execution_id` aligned with the existing execution recorder when one is active.
  - OpenProject event metadata stored in the request metadata.
- Platform execution uses `AgentExecutionRequest` with workflow ID `planning-session-{session_id}` and correlation ID set to the persisted event ID.
- `OrchestrationResult.workflow_result` now records platform result payload, route decision, and persisted result ID when the platform path is used.
- Execution-recorder completion maps platform agent results to `succeeded`, `waiting`, or `failed`.
- `/v1/events/{event_id}/orchestrate` now injects `AgentPlatformService` instead of constructing `PlanningWorkflowRunner` directly.
- Existing planning-runner behavior remains the fallback when no platform service is configured.

## Validation

Commands run:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_agent_platform_api.py tests/test_phase3_project_orchestrator.py tests/test_import_smoke.py
.venv/Scripts/python.exe -m ruff check agent_core/agent_core/application/project_orchestrator.py agent_core/agent_core/api/events.py tests/test_phase3_project_orchestrator.py tests/test_agent_platform_api.py
.venv/Scripts/python.exe -m pytest -q
```

Results:

- Event/API/import focused tests: 17 passed.
- Ruff: passed.
- Full test suite: 134 passed, 11 skipped, 4 existing warnings.

## Compatibility Notes

- `ProjectEventOrchestrator` still accepts `planning_runner` for compatibility.
- The platform path is selected only when `agent_platform_service` is supplied.
- Task-completion approvals continue to be recorded without starting coding/verification orchestration in this slice.
