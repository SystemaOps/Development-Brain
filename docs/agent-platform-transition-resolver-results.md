# Agent Platform Transition Resolver Results

## Summary

Database-backed platform services now include a production
`ApplicationAgentTransitionResolver`. It constructs typed requests for the next agent from durable
task context while keeping agent-specific translation outside the generic flow orchestrator.

## Implemented

- Added `AgentTaskTransitionContext` and `AgentTransitionContextStore`.
- Added `SqlAlchemyAgentTransitionContextStore`, which loads:
  - The selected project, plan version, task node, and acceptance criteria.
  - Planning approval state.
  - Context capsules and mapped external artifacts.
  - The latest coding checkpoint for the same workflow and task.
  - The latest platform coding result, with coding-attempt storage as fallback.
- Added `ApplicationAgentTransitionResolver` with typed request construction for:
  - Planning to coding.
  - Coding to verification.
  - Verification rework to coding.
  - Explicit replanning.
  - Same-agent retries.
- Wired the resolver into `create_agent_platform_service_for_db`.
- Preserved workflow ID, project ID, correlation ID, plan version, artifact references, and result
  lineage across handoffs.
- Added task-key checks so a coding attempt or result cannot be applied to a different task.

No schema migration was required because the adapter reads the existing plan, approval, context
capsule, checkpoint, result, artifact, and coding-attempt tables.

## Coding Attempt Contract

The current Coding Agent still executes an explicit `CodingAttemptRequest`. The resolver therefore
continues to coding only when an attempt has been persisted in a task context capsule.

Supported `capsule_json` keys:

- `prepared_coding_attempt` or the compatibility key `coding_attempt` for the initial attempt.
- `prepared_rework_attempt` or the compatibility key `rework_coding_attempt` for verification
  rework.

If an attempt, approval, task selection, task context, or acceptance criteria are unavailable, the
resolver returns no request and the flow reports `transition_pending`. It does not infer file edits
or silently select one task from a multi-task plan.

## Approval And Rework

- Planning-to-coding requires a persisted planning approval when the Planning Agent configuration
  enables the approval gate.
- Approval can also be represented by an approved or active plan version.
- When approvals are disabled by configuration, an explicit prepared coding attempt may continue.
- Verification rework requires an explicit prepared rework attempt. The prior patch is not repeated
  as though it were a corrective implementation.
- Same-agent retries reuse the original typed request with a new execution ID and the prior state
  reference.

## Validation

Commands run:

```powershell
.venv/Scripts/python.exe -m ruff check agent_core/agent_core/agent_platform/orchestration agent_core/agent_core/services/agent_transition_resolver.py agent_core/agent_core/persistence/agent_transition_context.py agent_core/agent_core/services/agent_platform_service.py agent_core/agent_core/api/agents.py tests/test_agent_transition_resolver.py tests/test_agent_transition_postgres_integration.py tests/test_agent_platform_api.py
.venv/Scripts/python.exe -m pytest -q tests/test_agent_transition_resolver.py tests/test_agent_transition_postgres_integration.py tests/test_agent_platform_flow.py tests/test_agent_platform_api.py tests/test_import_smoke.py
.venv/Scripts/python.exe -m pytest -q
```

Results:

- Ruff: passed.
- Focused tests without live PostgreSQL: 24 passed, 1 skipped.
- Live PostgreSQL transition-context integration: 1 passed.
- Full suite with PostgreSQL integrations enabled: 163 passed, 2 skipped, 4 existing warnings.
