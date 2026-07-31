# Agent Platform Architecture

This document describes the modular agent-platform foundation added on top of the existing `agent_core` package. The design is additive: existing FastAPI routes, services, skills, repository analysis, OpenProject, Neo4j, Weaviate, and coding-attempt behavior remain in place while new agents depend on stable platform contracts.

## Current Architecture Summary

The repository currently has a working planning-oriented application with these reusable pieces:

- `agent_core/skills/` contains modular planning skills for ingestion, requirement extraction, ambiguity assessment, decomposition, validation, repository inspection, OpenProject projection, Neo4j projection, Weaviate projection, and context capsules.
- `agent_core/services/` contains application services for planning sessions, documents, context capsules, repository analysis, repository projection, and coding attempts.
- `agent_core/ports/` already defines infrastructure ports for project repositories, events, approvals, artifacts, OpenProject, graph storage, vector storage, repository filesystem, repository analysis, command execution, LLM generation, and coding attempts.
- `agent_core/adapters/` contains concrete adapters for OpenProject, Neo4j, Weaviate, repository filesystem, command execution, Tree-sitter extraction, LSP lookup, and repository analysis.
- `agent_core/workflow/` contains the existing planning LangGraph workflow and remains a compatibility path.

The new platform package does not replace those pieces. It wraps and organizes them behind agent lifecycle contracts and dependency injection.

## Target Package Boundary

The platform root is `agent_core/agent_platform/`.

```text
agent_platform/
  agents/
    base/
    planning/
    coding/
    verification/
  factory/
  orchestration/
  runtime/
  adapters/
    llm/
    postgres/
    neo4j/
    weaviate/
    openproject/
    git/
    filesystem/
    command_runner/
  config/
```

Important boundary rules:

- Agents depend on `agents/base`, `runtime`, typed request/result models, skills, and injected dependencies.
- Agents do not import concrete database, OpenProject, Neo4j, Weaviate, Git, filesystem, command-runner, or LLM clients directly.
- The orchestrator depends on common contracts and the factory, not on agent-specific business logic.
- Agent modules own their request/result/state/workflow definitions.
- Skills remain reusable units and do not depend on whole agent objects.

Application code can use `agent_core/services/agent_platform_service.py` as the migration entry point for invoking the platform without directly constructing the factory and orchestrator.

FastAPI exposes one-step compatibility execution through `POST /v1/agents/execute`. Durable
multi-agent flows use:

- `POST /v1/agents/flows` to reserve and execute a new flow.
- `POST /v1/agents/flows/async` to persist a queued flow and return `202 Accepted`.
- `GET /v1/agents/flows/by-workflow` to discover a flow after a failed start response.
- `GET /v1/agents/flows/{flow_id}` to inspect its aggregate state and audit history.
- `POST /v1/agents/flows/{flow_id}/heartbeat` to extend an active running lease.
- `POST /v1/agents/flows/{flow_id}/recover` to claim and replay an expired running execution.
- `POST /v1/agents/flows/{flow_id}/resume` to record approval evidence or supply the next typed
  request.

The routes accept a discriminated union of Planning, Coding, and Verification requests, create
request-scoped durable stores, and invoke `AgentPlatformService`.

OpenProject event orchestration uses the same service for resumable planning events. `ProjectEventOrchestrator` builds a typed `PlanningAgentRequest` from the persisted event and waiting planning session, then invokes the platform orchestrator instead of directly calling the planning workflow runner when `agent_platform_service` is configured.

## Common Agent Lifecycle

All concrete agents implement `BaseAgent`:

```python
class BaseAgent(ABC):
    @property
    @abstractmethod
    def agent_type(self) -> str: ...

    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def validate_request(self, request: AgentRequest) -> None: ...

    @abstractmethod
    async def execute(self, request: AgentRequest, context: AgentExecutionContext) -> AgentResult: ...

    @abstractmethod
    async def shutdown(self) -> None: ...
```

The lifecycle helper runs `initialize`, `validate_request`, `execute`, and `shutdown` consistently.

## Shared Contracts

Cross-agent communication uses typed Pydantic models:

- `AgentRequest`
- `AgentResult`
- `ArtifactReference`
- `StateReference`
- `AgentError`
- `AgentExecutionContext`
- `CheckpointIdentity`
- `AgentLifecycleEvent`

Specialized agents extend the base contracts:

- `PlanningAgentRequest` and `PlanningAgentResult`
- `CodingAgentRequest` and `CodingAgentResult`
- `VerificationAgentRequest` and `VerificationAgentResult`

The one-step orchestrator accepts `AgentExecutionRequest` and returns `AgentOrchestrationResult`.
It preserves specialized subclass payloads using Pydantic `SerializeAsAny` while still enforcing
the common base contract. `AgentFlowOrchestrator` composes these one-step runs into a bounded flow
and returns `AgentFlowResult` with the complete step history and final pause or completion status.
Durable flow boundaries use `PersistedAgentFlow`, `AgentFlowStepRecord`, `AgentFlowApproval`,
`AgentFlowLease`, and `AgentFlowRecoveryRecord`. Raw request/result payloads are stored only as
audit and recovery data; agents still communicate through typed contracts.

Each concrete agent delegates execution to a separately compiled LangGraph:

- `planning-agent-workflow`
- `coding-agent-workflow`
- `verification-agent-workflow`

The graphs use agent-specific Pydantic workflow state and typed `AgentWorkflowRuntime` context.
Dependencies and execution metadata are runtime context, not shared graph-state fields. The graphs
return the existing specialized result contracts to the orchestrator and never invoke one another.

## Agent Responsibilities

Planning Agent:

- Extracts requirements from the objective and provided document chunks.
- Optionally wraps the existing planning service for session-based plan drafting.
- Validates provided or generated plans using `PlanValidationSkill`.
- Returns approval, clarification, or coding transitions through `next_action`.
- Saves independent planning state through the checkpoint store.

Coding Agent:

- Requires an approved task-scoped `CodingAttemptRequest`.
- Delegates bounded implementation execution to the injected coding service.
- Records changed files, command evidence, errors, final diff, and rollback data.
- Returns verification, retry, or escalation transitions.
- Does not redefine requirements or expand task scope.

Verification Agent:

- Loads the original acceptance criteria and coding result or diff.
- Evaluates the actual diff, command evidence, and coding status independently from the coding summary.
- Composes dependency-free typed skills for mandatory acceptance coverage, test adequacy,
  regression risk, security/configuration review, and final evidence summarization.
- Persists each typed assessment in its independent checkpoint state and includes the assessments
  in `VerificationAgentResult`.
- Optionally pauses eligible negative verdicts for a human override without changing the original
  result, findings, or evidence.
- Produces one of `passed`, `passed_with_warnings`, `changes_requested`, or `blocked`.
- Returns completion, coding rework, or escalation transitions.

Verification skills do not import the agent or workflow. Graph nodes translate request data into
skill input contracts and append returned findings. Failed commands, unsatisfied acceptance
criteria, and error-level security findings prevent completion. Requirements for an executed test
command and source-change test evidence are configurable to support gradual migration.

Human override is disabled by default. When enabled, `VerificationAgentConfig` limits eligible
verdicts and the agent requests an approval gate. `AgentPlatformService` reconstructs policy from
the persisted Verification step before accepting a `VerificationOverrideCommand`. A successful
override completes the flow and appends an `AgentFlowOverrideRecord`; it does not replace the
failed source result. The audit captures source identities, original outcome, finding and
criterion keys, actor, reason, reference, metadata, and timestamp.

## Factory And Registration

Agent creation is registry-based. `AgentFactory` has no large conditional block.

```python
factory = create_default_agent_factory(dependencies)
agent = factory.create(
    agent_type="planning",
    config=config.agents["planning"],
)
```

Default registration is implemented by each agent module exposing a `register_*_agent` function. The default factory calls those registration functions.

Adding a new agent requires:

1. Implementing `BaseAgent`.
2. Adding request, result, state, workflow, and config models.
3. Adding an `AgentBuilder`.
4. Registering the builder.

Example fourth agent:

```python
class SecurityReviewAgentBuilder:
    @property
    def agent_type(self) -> str:
        return "security_review"

    def build(self, *, config: AgentConfig, dependencies: AgentDependencyContainer) -> BaseAgent:
        return SecurityReviewAgent(config=config, dependencies=dependencies)

factory.register(
    "security_review",
    SecurityReviewAgentBuilder(),
)

agent = factory.create(
    agent_type="security_review",
    config=config.agents["security_review"],
)
```

No orchestrator changes are required.

## Orchestration

`AgentOrchestrator` is intentionally lightweight. It performs platform coordination only:

- Creates an `AgentExecutionContext`.
- Uses the factory to create the requested agent.
- Emits lifecycle events.
- Runs the common lifecycle helper.
- Persists the result through an injected result store.
- Converts exceptions into structured failed `AgentResult` objects and preserves a checkpoint entry.
- Computes a high-level route from `AgentNextAction`.

`AgentFlowOrchestrator` adds high-level sequencing without adding agent business logic. It:

- Runs `AgentOrchestrator.run_once` for each step.
- Stops at approval, clarification, escalation, completion, or a configured step limit.
- Routes retry to the agent that produced the retry result.
- Uses an injected `AgentTransitionRequestResolver` to obtain the next specialized request.
- Rejects handoffs that change the workflow ID or project ID.
- Returns `transition_pending` when the next typed request is not available yet.

The transition resolver is an application-layer boundary. It may load artifacts, acceptance
criteria, coding results, or approval records and convert them into the next agent's request. The
generic orchestrator only checks that the returned request matches the requested route and retains
flow identity.

Database-backed application composition uses `ApplicationAgentTransitionResolver` with
`SqlAlchemyAgentTransitionContextStore`. The store reads the selected plan task, acceptance
criteria, approval state, context capsules, external artifacts, coding checkpoints, and coding
results. The resolver then constructs the specialized Planning, Coding, or Verification request.
It pins downstream lookup to the plan version propagated in transition metadata.

Because the current Coding Agent requires an explicit `CodingAttemptRequest`, coding transitions
only continue when a context capsule contains `prepared_coding_attempt` for initial work or
`prepared_rework_attempt` for verification rework. Missing durable input produces
`transition_pending`; the resolver does not invent file changes.

Agents never call each other directly. The orchestrator maps next actions to route decisions:

- `run_planning` routes to Planning Agent.
- `run_coding` routes to Coding Agent.
- `run_verification` routes to Verification Agent.
- `request_approval` pauses for an approval gate.
- `request_clarification` or `escalate` pauses for human intervention.
- `complete` ends the flow.

`AgentPlatformService.execute` remains the one-step compatibility entry point.
`AgentPlatformService.execute_flow` runs the bounded flow. When an `AgentFlowStore` is injected, it
reserves the aggregate before invoking an agent and commits the resulting step history afterward.
`start_flow` requires persistence and returns the durable snapshot. `resume_flow` claims the
expected aggregate version before running the next typed request.

`enqueue_flow` persists the same typed request with `queued` status and its bounded execution
options without invoking an agent. `AgentFlowWorker` claims queued rows with PostgreSQL
`FOR UPDATE SKIP LOCKED`, decodes the request through a registry-backed codec, and calls
`execute_claimed_flow`. Agents remain unaware of the worker and do not call one another.

Every running claim has a unique lease token, owner, acquisition time, and expiry. Completion must
present the current token and aggregate version. Heartbeat extends the same token without changing
the version. Recovery is permitted only after lease expiry, requires an exact replay of the
persisted typed execution request, replaces the token, increments the version, and records both
leases in append-only recovery history. A stale worker can therefore no longer commit.
The background worker uses a separate SQLAlchemy session for execution and for each heartbeat.
Expired claims are recovered only when configured, and bounded automatic recovery transitions an
exhausted flow to `escalated` while retaining its pending request.

Approval is data, not an implicit flag. A flow waiting for approval requires an
`AgentFlowApproval` containing a decision and stable external reference. Approved flows require a
typed continuation request. `changes_requested` and `cancelled` decisions close the current flow
without invoking another agent. Agents never consume approvals by calling one another directly.

## State And Checkpointing

State is separated into three layers:

- Agent workflow state: agent-specific Pydantic state models.
- Cross-agent metadata: `AgentExecutionContext`, lifecycle events, persisted results, and the
  durable flow aggregate.
- Long-term project memory: existing domain stores, artifacts, OpenProject, Neo4j, and Weaviate.

Checkpoint identity includes:

- `project_id`
- `workflow_id`
- `agent_type`
- `agent_instance_id`
- `execution_id`
- `thread_id`
- `checkpoint_id`

The current implementation includes `InMemoryCheckpointStore` for tests and local contract
validation. `SqlAlchemyAgentCheckpointStore` persists platform checkpoints in
`agent_platform_checkpoints`. Every meaningful internal graph node saves its agent-specific state
through this port. `workflow_trace` records node progress independently from the business `phase`.
If graph execution fails, the structured failure checkpoint retains the prior node state under
`last_workflow_state`.

Agent results can be stored through `SqlAlchemyAgentResultStore`, which writes typed result payloads to `agent_platform_results`. The orchestrator uses `dependencies.result_store` when no explicit result store is supplied.

`SqlAlchemyAgentFlowStore` writes the aggregate to `agent_platform_flows`. Each mutation locks the
row and checks the caller's expected version. Claims and completions increment the version;
heartbeat only extends the current token. The JSONB payload preserves
the complete step, approval, lease, and recovery history, while relational columns index status,
current execution, pending action, pending agent, approval state, correlation, resume count,
recovery count, lease identity, owner, and expiry. A unique
`(project_key, workflow_id)` constraint prevents duplicate flow creation.

Flow and agent checkpoints remain separate. A flow record coordinates high-level transitions; it
does not replace agent-specific checkpoint namespaces or long-term project memory. If agent
execution raises after reservation, the running aggregate retains the pending typed request for
diagnosis and recovery instead of losing execution identity.

Migration `0013_agent_flow_recovery_leases` marks legacy running rows as immediately expired and
recoverable. Paused and completed rows remain unleased. Database reads merge the indexed lease
columns into legacy JSON aggregates until the next aggregate write normalizes the JSON payload.

Migration `0014_queued_agent_flows` adds the `queued` aggregate status. PostgreSQL is the durable
flow queue; no second queue message must be reconciled with the aggregate.

These platform checkpoints remain separate from native LangGraph snapshots. PostgreSQL-backed
LangGraph checkpointing remains available in the compatibility workflow package and can be adopted
per agent later for native interrupts or node replay without creating one cross-agent graph.

## Adapters And Dependency Injection

`AgentDependencyContainer` provides shared infrastructure to agents through constructor injection and execution context. It defaults to in-memory checkpoint and event-bus implementations for tests.

Platform adapter namespaces expose interfaces for:

- `LLMClient`
- `ExecutionRepository`
- `ArtifactRepository`
- `ApprovalRepository`
- `ProjectRepository`
- `CodingAttemptRepository`
- `GraphRepository`
- `SemanticContextStore`
- `WorkPackageGateway`
- `GitRepository`
- `RepositoryBindingStore`
- `RepositoryAnalysisGateway`
- `SyntaxExtractionGateway`
- `LspLookupGateway`
- `FilesystemWorkspace`
- `CommandRunner`

Most are aliases over existing `agent_core.ports` protocols, so concrete adapters do not need to move immediately.

## Configuration

The platform configuration is represented by:

- `AgentConfig`
- `AgentPlatformConfig`
- `AgentFlowRuntimeConfig`
- `LLMEndpointConfig`

The loader accepts JSON, discovers the runtime path from `AGENT_PLATFORM_CONFIG_FILE`, and returns
a deep copy of the default config when no explicit or environment path is provided. Example
configuration is in `agent_core/agent-platform.example.json`.

The LLM endpoint remains configurable by:

- `base_url`
- `model`
- `timeout_seconds`
- `context_window`

No llama.cpp endpoint is hard-coded.

Flow runtime configuration controls:

- `lease_seconds`
- `heartbeat_seconds`
- `worker_poll_seconds`
- `recovery_enabled`
- `max_recovery_attempts`

For synchronous API execution, `lease_seconds` must exceed the longest expected run. An external
worker that owns a long-running claim should heartbeat before expiry. The included
`agent-flow-worker` performs heartbeats automatically for flows accepted through
`POST /v1/agents/flows/async`.

## Observability

The platform emits structured lifecycle events:

- `agent.created`
- `agent.started`
- `agent.step.started`
- `agent.step.completed`
- `agent.interrupted`
- `agent.failed`
- `agent.completed`
- `agent.result.persisted`
- `agent.transition.requested`

Every event includes execution, project, task, agent, instance, timestamp, status, step, and correlation fields. The default test implementation stores events in memory. A structured logging event bus writes JSON records.

## Testing Strategy

The new platform test suite covers:

- Registered agents implement `BaseAgent`.
- Factory registration, duplicate registration, unknown agent type, disabled config, and builder mismatch handling.
- Valid request acceptance and invalid request rejection.
- Result contract validation for planning, coding, and verification.
- Orchestration transitions for planning approval, coding to verification, verification rework, verification blocked, planning clarification, and coding blocked.
- Multi-step flow completion, approval and clarification pauses, pending transition input,
  retry limits, and cross-workflow handoff rejection.
- Durable reserve/complete transitions, append-only step numbering, audited approval resume and
  rejection, optimistic version conflicts, and pending-request preservation on execution failure.
- Active-lease takeover rejection, heartbeat renewal without version churn, exact-request recovery,
  stale-token completion rejection, recovery-disable configuration, and workflow discovery.
- Queued execution, typed request decoding, independent heartbeat sessions, oldest-first concurrent
  claims, bounded automatic recovery, and exhausted-flow escalation.
- Production transition resolution from persisted tasks, approvals, context capsules, coding
  checkpoints, and coding results.
- Live PostgreSQL flow persistence, JSONB reloading, indexed aggregate fields, and migration-head
  validation.
- Checkpoint namespace isolation and failure checkpoint preservation.
- Independent Planning, Coding, and Verification graph topology, conditional routing, node traces,
  and partial-state preservation.

The tests use fake dependencies and do not require Docker, OpenProject, Neo4j, Weaviate, or a live LLM.
