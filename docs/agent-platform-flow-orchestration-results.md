# Agent Platform Flow Orchestration Results

## Summary

The platform now supports bounded multi-agent execution on top of the existing one-agent
`run_once` path. A flow can advance from planning to coding to verification, route verification
rework back to coding, retry the current agent, and stop safely at approval, clarification,
escalation, missing transition input, or a configured step limit.

## Implemented

- Added typed `AgentFlowStep`, `AgentFlowResult`, `AgentFlowStatus`, and
  `AgentTransitionRequestResolver` contracts.
- Added `AgentFlowOrchestrator`, which delegates each agent run to `AgentOrchestrator` and never
  creates agent-specific requests itself.
- Added `InMemoryTransitionRequestResolver` for deterministic tests and explicitly assembled local
  flows.
- Added `AgentPlatformService.execute_flow` as the application-facing multi-step entry point.
- Preserved `AgentPlatformService.execute` and `AgentOrchestrator.run_once` for one-agent and
  compatibility callers.
- Added the original `next_action` to `AgentRouteDecision` so flow consumers do not need to infer
  clarification, completion, or retry semantics from loosely related fields.
- Corrected retry routing so `retry` targets the current agent.
- Added validation that execution, request, and configuration agent types match.
- Added handoff validation that preserves workflow and project identity across agents.

## Transition Boundary

Agents continue to return typed results and never call each other. The flow orchestrator determines
whether execution may continue, but an injected transition resolver builds the next specialized
request from persisted artifacts and prior results. This keeps planning, coding, and verification
payload knowledge in the application composition layer.

If a resolver is absent or cannot yet provide the request, the flow returns `transition_pending`
with the pending route. Approval and clarification produce their own waiting statuses. Durable
callers continue the same aggregate through `AgentPlatformService.resume_flow` or
`POST /v1/agents/flows/{flow_id}/resume`, passing the current version and a typed request that
preserves project and workflow identity.

Database-backed platform construction now supplies `ApplicationAgentTransitionResolver` by
default. Its implementation and persisted context contract are recorded in
`docs/agent-platform-transition-resolver-results.md`.

## Durable Aggregate

`AgentFlowOrchestrator` remains persistence-independent. `AgentPlatformService` wraps it with an
injected `AgentFlowStore`:

1. Reserve a running aggregate and pending request at version 1.
2. Run one or more bounded agent steps.
3. Append raw audit records and commit the resulting status at version 2.
4. Claim a paused flow using its expected version, recording approval evidence when applicable.
5. Execute the typed continuation and append its steps without overwriting prior history.

`InMemoryAgentFlowStore` supports deterministic unit tests.
`SqlAlchemyAgentFlowStore` uses row locking, optimistic versions, a unique project/workflow
identity, indexed state columns, and a JSONB aggregate in `agent_platform_flows`.

Approval rejection and cancellation close the aggregate without running another agent. Execution
exceptions leave the pre-committed running record and pending request available for diagnosis.
Detailed implementation and validation are recorded in
`docs/agent-platform-flow-persistence-results.md`.

## Validation

Commands run:

```powershell
.venv/Scripts/python.exe -m ruff check agent_core/agent_core/agent_platform/orchestration agent_core/agent_core/services/agent_platform_service.py tests/test_agent_platform_flow.py
.venv/Scripts/python.exe -m pytest -q tests/test_agent_flow_persistence.py tests/test_agent_platform_api.py tests/test_agent_platform_flow.py
.venv/Scripts/python.exe -m pytest -q
```

Results:

- Ruff: passed.
- Focused persistence, API, and flow tests: 23 passed.
- Full test suite with PostgreSQL integrations enabled: 183 passed, 2 skipped, 4 existing
  warnings.
