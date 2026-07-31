# Agent Platform Migration Notes

The platform refactor is additive. The current APIs, service classes, workflow modules, persistence models, adapters, and tests remain available while callers migrate to `agent_core.agent_platform`.

## Migration Map

Current planning runtime:

- Keep `agent_core/workflow/*` as the existing LangGraph planning workflow.
- New platform requests run through the independent Planning Agent graph. It can still use the
  injected legacy `planning_service` for session-based plan generation.
- Keep planning skills in `agent_core/skills/*`; agent-specific planning modules compose them rather than copying logic.

Current coding runtime:

- Keep `agent_core/services/coding_service.py` as the bounded write and quality-command executor.
- Use `CodingAgent` as the lifecycle wrapper around one approved `CodingAttemptRequest`.
- Continue persisting attempts through the existing coding-attempt repository and migration.

Current verification behavior:

- Keep `VerificationAgent` as an independent contract-first verifier.
- Its graph composes agent-local typed skills for acceptance coverage, test adequacy, regression
  risk, security/configuration review, and final evidence summarization.
- New assessment fields on `VerificationAgentState` and `VerificationAgentResult` have defaults, so
  existing persisted results and manually built contracts remain valid.
- Stricter test-execution requirements and regression warnings are opt-in. Security review remains
  enabled by default and error-level findings request coding changes.
- Human override is disabled by default. Enabling it for selected negative verdicts changes the
  next action to an approval gate but does not mutate the original Verification result.
- Applied overrides are appended to durable flow JSON as typed `AgentFlowOverrideRecord` entries.
  Existing rows remain readable because the new list defaults to empty.

Current repository analysis:

- Keep concrete Tree-sitter and LSP adapters in `agent_core/adapters/*`.
- Expose platform-facing interfaces through `agent_platform/adapters/git`.
- Continue repository binding and indexing through existing repository services until orchestration endpoints are migrated.

Current infrastructure ports:

- Reuse `agent_core/ports/*` as the source of truth for dependency inversion.
- Re-export platform-facing adapter interfaces under `agent_platform/adapters/*` for discoverability.
- Do not import concrete clients in agent business logic.

## Files Added

- `agent_core/agent_core/agent_platform/agents/base/*`
- `agent_core/agent_core/agent_platform/agents/planning/*`
- `agent_core/agent_core/agent_platform/agents/coding/*`
- `agent_core/agent_core/agent_platform/agents/verification/*`
- `agent_core/agent_core/agent_platform/factory/*`
- `agent_core/agent_core/agent_platform/orchestration/*`
- `agent_core/agent_core/agent_platform/runtime/*`
- `agent_core/agent_core/agent_platform/config/*`
- `agent_core/agent_core/agent_platform/adapters/*`
- `agent_core/agent_core/api/agents.py`
- `agent_core/agent_core/services/agent_platform_service.py`
- `agent_core/agent_core/persistence/agent_platform.py`
- `agent_core/agent_core/persistence/agent_flows.py`
- `agent_core/agent-platform.example.json`
- `agent_core/alembic/versions/0011_agent_platform_persistence.py`
- `agent_core/alembic/versions/0012_agent_platform_flows.py`
- `agent_core/alembic/versions/0013_agent_flow_recovery_leases.py`
- `agent_core/alembic/versions/0014_queued_agent_flows.py`
- `agent_core/agent_core/workers/agent_flow_worker.py`
- `agent_core/agent_core/services/agent_execution_codec.py`
- `agent_core/agent_core/services/agent_platform_composition.py`
- `agent_core/agent_core/agent_platform/agents/base/workflow.py`
- `tests/test_agent_internal_workflows.py`
- `tests/test_agent_platform.py`
- `tests/test_agent_flow_persistence.py`
- `tests/test_agent_flow_postgres_integration.py`
- `docs/agent-platform-architecture.md`
- `docs/agent-platform-migration-notes.md`

## Files Modified

- `agent_core/agent_core/skills/__init__.py` now lazy-loads skill implementations to avoid environment-dependent imports when individual skill submodules are imported.
- `tests/test_import_smoke.py` now covers the new agent-platform package.
- `docs/refactoring-implementation-plan.md` references this platform milestone.
- `agent_core/agent_core/models.py` now includes platform checkpoint, result, and
  aggregate flow records.
- `agent_core/agent_core/main.py` now includes the agents router.
- `agent_core/agent_core/application/project_orchestrator.py` can route resumable planning events through `AgentPlatformService`.
- Planning, Coding, and Verification `workflow.py` modules now compile independent LangGraph state
  machines; their `agent.py` modules retain lifecycle, validation, and builder responsibilities.

## Compatibility Risks

- Some callers may have relied on importing skill classes directly from `agent_core.skills`. Current repository tests only import `build_skill_registry` from that package root. If external callers require root-level skill class imports, add explicit lazy accessors or compatibility exports.
- `PlanningAgent` can wrap the legacy planning service, but the existing planning workflow remains the richer production path until all planning skills are wired into the agent workflow.
- Platform checkpoints persist the latest completed graph phase rather than native LangGraph
  channel snapshots. Adopt native per-agent checkpointers only when interrupts or node replay are
  required; do not introduce one shared cross-agent graph.
- `VerificationAgent` is intentionally conservative. Missing diffs or blocked coding attempts route to escalation rather than guessing.
- In-memory checkpointing, results, and flow stores remain available for tests. Database-backed API
  composition injects PostgreSQL implementations for all three.
- `agent_platform_flows` stores serialized typed requests and results for audit/recovery. Deployments
  must apply their normal secret-redaction and retention policy to request metadata and artifacts.
- Recovery replays must use the exact pending execution payload. Callers should fetch the aggregate
  by flow ID or workflow identity instead of constructing a replacement objective or configuration.
- Automatic recovery can repeat idempotent agent work after a lost lease. Keep external writes
  idempotent, configure a bounded attempt count, and monitor flows that transition to `escalated`.
- Agent config currently uses JSON loading. YAML can be added later if a dependency is acceptable.

## Migration Steps

1. Keep existing API routes and services stable.
2. Introduce platform construction in application composition using `create_default_agent_factory(dependencies)`.
3. Wrap current planning requests in `PlanningAgentRequest` and invoke through `AgentOrchestrator.run_once` for new flows.
4. Route persisted OpenProject planning feedback through `ProjectEventOrchestrator` with `agent_platform_service`.
5. Wrap approved coding attempts in `CodingAgentRequest` and invoke through the same orchestrator.
6. Feed coding results and original acceptance criteria into `VerificationAgentRequest`.
7. Persist explicit initial or rework `CodingAttemptRequest` payloads in task context capsules when
   automatic coding transitions are required.
8. Use `AgentPlatformService.start_flow` or `POST /v1/agents/flows` for new durable flows; keep
   `execute` for event-driven single-step compatibility.
9. Resume the same `flow_id` with its current `version`, explicit approval evidence where required,
   and a typed request matching the stored workflow and pending agent.
10. Apply Alembic migration `0012_agent_platform_flows` before enabling the durable endpoints.
11. Apply migration `0013_agent_flow_recovery_leases`, configure `flow_runtime.lease_seconds`, and
    decide whether recovery is enabled.
12. Heartbeat long-running externally owned claims before expiry; recover only expired claims using
    their exact pending request.
13. Apply migration `0014_queued_agent_flows` and start `agent-flow-worker` before sending requests
    to `POST /v1/agents/flows/async`.
14. Configure heartbeat, polling, recovery enablement, and bounded recovery attempts under
    `flow_runtime`.
15. Move OpenProject, Neo4j, Weaviate, and repository indexing triggers behind orchestrator-driven events.
16. Add richer agent workflows internally without changing factory or orchestrator code.
17. Retire legacy direct workflow entry points only after API and integration tests prove parity.

## Example Flow

```python
from agent_core.agent_platform import AgentDependencyContainer
from agent_core.agent_platform.factory import create_default_agent_factory
from agent_core.agent_platform.orchestration import AgentExecutionRequest
from agent_core.services.agent_platform_service import AgentPlatformService

config = load_agent_platform_config("agent_core/agent-platform.example.json")
dependencies = AgentDependencyContainer(
    coding_service=coding_service,
    planning_service=planning_service,
    graph_repository=neo4j_repository,
    context_store=weaviate_store,
    work_package_gateway=openproject_gateway,
)
factory = create_default_agent_factory(dependencies)
service = AgentPlatformService(
    dependencies=dependencies,
    factory=factory,
    transition_resolver=application_transition_resolver,
    flow_store=flow_store,
)

flow = await service.start_flow(
    AgentExecutionRequest(
        workflow_id="project-demo-task-42",
        agent_type="planning",
        request=planning_request,
        config=config.agents["planning"],
    ),
    max_steps=10,
)
```

The resulting durable flow records every agent step and returns a typed status when it completes
or pauses. Call `resume_flow` with `flow.flow_id`, `flow.version`, approval evidence when required,
and the next typed execution request.
The application transition resolver converts persisted artifacts into the next agent's typed
request. The previous agent never calls the next agent directly.

Database-backed services created by `create_agent_platform_service_for_db` already inject the
production transition resolver. Initial coding uses the `prepared_coding_attempt` context-capsule
key; verification rework uses `prepared_rework_attempt`.

## Fourth-Agent Registration Example

```python
factory.register(
    "security_review",
    SecurityReviewAgentBuilder(dependencies),
)

agent = factory.create(
    agent_type="security_review",
    config=config.agents["security_review"],
)
```

The security review agent can add its own `SecurityReviewAgentRequest`, `SecurityReviewAgentResult`, state model, workflow, skills, and validation rules while preserving the common lifecycle contract.
