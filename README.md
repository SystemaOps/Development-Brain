# Modular Coding Agent System

> **Implementation specification for Codex**  
> This document is the authoritative implementation brief for extending the existing repository into a modular, persistent, event-driven coding-agent system containing planning, coding, and verification agents.

## 1. Codex mandate

Implement the system described in this document in the **existing repository**. Do not create an unrelated replacement project. Begin by inspecting the current code, tests, Docker Compose files, database initialization scripts, and existing OpenProject integration. Preserve working behavior and migrate incrementally.

The implementation must prioritize:

- long-term extensibility;
- typed module boundaries;
- deterministic and inspectable orchestration;
- replaceable skills and infrastructure adapters;
- persistent workflow execution;
- traceability from requirement to task, code, test, and verification evidence;
- safe recovery from process restarts and duplicate webhook delivery;
- explicit human instructions, approvals, and feedback through OpenProject;
- a complete planning, coding, and verification flow;
- support for repositories mounted into the agent containers.

The implementation must not depend on hosting or starting an LLM. A `llama.cpp` server is already hosted externally. The application only requires configuration for its base URL, model name, optional API key, timeout, and generation settings.

## 2. Existing repository

The repository currently has the following high-level structure:

```text
.
├── infra
│   ├── agent_trigger
│   │   └── app
│   ├── models
│   ├── openproject
│   │   └── provision
│   ├── postgres
│   │   └── init
│   ├── scripts
│   └── workspace
├── agent_core
│   └── agent_core
│       ├── adapters
│       ├── api
│       ├── ingestion
│       ├── services
│       ├── skills
│       └── workflow
└── sample_project
```

### 2.1 Migration rule

Codex must first produce a short repository assessment in `docs/current-state-assessment.md` covering:

1. existing modules and their responsibilities;
2. code that is already usable;
3. code that should be moved or wrapped;
4. duplicate or obsolete implementations;
5. existing database and webhook contracts;
6. test coverage and known gaps;
7. migration risks.

Do not delete an existing module merely because the target structure differs. Prefer this order:

1. add a stable interface;
2. wrap the existing implementation behind it;
3. migrate callers;
4. add tests;
5. remove the obsolete path only after no production code references it.

Keep the Python distribution and import root `agent_core` for the initial migration. Although the package will contain more than a planning agent, renaming the distribution now would introduce unnecessary migration risk. Record a possible future rename in an architectural decision record, but do not make it a prerequisite.

## 3. System goals

The completed system must be able to:

1. receive OpenProject webhook events;
2. persist each event before processing it;
3. associate an OpenProject project with a mounted source repository;
4. ingest documents, task descriptions, story descriptions, comments, and repository context;
5. extract and normalize requirements;
6. identify blocking ambiguities and request clarification through OpenProject;
7. inspect an existing implementation and classify requirements or tasks as complete, partial, missing, conflicting, or unverifiable;
8. create or update a structured implementation plan;
9. project epics, stories, tasks, dependencies, descriptions, acceptance criteria, and status into OpenProject;
10. react to human edits and comments in OpenProject as new instructions or feedback;
11. select an approved task and create a bounded context capsule;
12. change code only inside the mounted repository and configured write scope;
13. run configured quality checks and tests;
14. verify implementation against requirements and acceptance criteria;
15. update OpenProject with progress, evidence, blockers, and final outcomes;
16. persist checkpoints so interrupted workflows can resume;
17. preserve complete auditability across agent runs and skill runs;
18. support adding or replacing a skill without rewriting the complete workflow.

## 4. Explicit non-goals for the first implementation

Do not add the following unless required by an already-working part of the repository:

- a custom frontend;
- end-user registration or account management;
- a hosted LLM service inside Docker Compose;
- automatic deployment to production;
- unrestricted shell access;
- arbitrary execution outside mounted repositories;
- autonomous merge to protected branches;
- direct dependence of domain logic on OpenProject, Neo4j, Weaviate, Redis, or `llama.cpp` client classes;
- dynamically generated workflow topology with no predefined policy boundaries.

## 5. Architectural principles

### 5.1 Separation of responsibilities

Use the following definitions consistently:

- **Agent definition:** objective, permissions, allowed skills, workflow, limits, and configuration.
- **Workflow:** lifecycle, branching, retries, interruptions, resumptions, and transitions.
- **Skill:** meaningful business capability with typed input and output.
- **Tool:** small external operation such as reading a file, running a test, or updating a work package.
- **Port:** technology-independent interface required by domain or application code.
- **Adapter:** implementation of a port for a concrete technology.
- **Policy:** explicit rule controlling access, transitions, approval, or side effects.
- **Checkpoint:** persisted workflow execution state.
- **Domain state:** durable business data that remains authoritative independently of a workflow checkpoint.
- **Context capsule:** bounded, task-specific context assembled for one agent action.
- **Evidence:** reference proving why the system classified, changed, or verified something.

The key rule is:

```text
Workflows decide when work occurs.
Skills define how a business capability is performed.
Tools perform narrowly scoped external operations.
Policies decide what is allowed.
Ports prevent domain logic from depending on vendors.
```

### 5.2 Dependency direction

Dependencies must point inward:

```text
API / Workers / CLI
        ↓
Application services and workflows
        ↓
Domain models, skill contracts, policies, and ports
        ↑
Infrastructure adapters implement ports
```

Domain and skill-contract modules must not import:

- FastAPI;
- SQLAlchemy ORM models;
- OpenProject clients;
- Neo4j drivers;
- Weaviate clients;
- Redis clients;
- concrete LLM SDKs.

### 5.3 Stable contracts over stable implementations

A workflow must depend on a stable skill name and typed contract, not a specific prompt or implementation class.

Example:

```python
skill = skill_registry.resolve("requirement_extraction")
result = await skill.execute(context, skill_input)
```

Do not hard-code imports such as `RequirementExtractionPromptV1` inside workflow nodes.

### 5.4 Prefer deterministic control around probabilistic reasoning

Use deterministic code for:

- validation;
- authorization;
- transition checks;
- event deduplication;
- schema conversion;
- file path validation;
- dependency ordering;
- state updates;
- idempotency;
- test execution;
- calculation of status from evidence.

Use the LLM for bounded reasoning tasks such as:

- requirement extraction;
- ambiguity analysis;
- plan decomposition;
- code-change proposals;
- failure interpretation;
- comparison of implementation evidence with acceptance criteria.

Every LLM-produced structure must be validated using Pydantic before use.

## 6. Target system overview

```text
┌───────────────────────────────────────────────────────────────────────┐
│ Human users and external systems                                    │
│ OpenProject UI, OpenProject API/webhooks, mounted source repository │
└───────────────────────────────────┬───────────────────────────────────┘
                                    │
                           webhook / API request
                                    │
┌───────────────────────────────────▼───────────────────────────────────┐
│ infra/agent_trigger                                                  │
│ Validate envelope → persist inbox event → enqueue event reference    │
└───────────────────────────────────┬───────────────────────────────────┘
                                    │ Redis queue / durable event id
┌───────────────────────────────────▼───────────────────────────────────┐
│ Agent worker and project orchestrator                                │
│ Load project binding → classify event → start or resume workflow     │
└───────────────┬───────────────────┬───────────────────┬───────────────┘
                │                   │                   │
       ┌────────▼────────┐ ┌────────▼────────┐ ┌────────▼─────────┐
       │ Planning graph │ │ Coding graph   │ │ Verification graph│
       └────────┬────────┘ └────────┬────────┘ └────────┬─────────┘
                │                   │                   │
       ┌────────▼───────────────────▼───────────────────▼─────────┐
       │ Skill registry, tool registry, policies, context service │
       └────────┬───────────────────┬───────────────────┬─────────┘
                │                   │                   │
       ┌────────▼───────┐  ┌────────▼───────┐  ┌────────▼────────┐
       │ PostgreSQL     │  │ Neo4j          │  │ Weaviate        │
       │ domain + event │  │ relationships  │  │ semantic memory│
       │ + checkpoints  │  │ and evidence  │  │ and retrieval   │
       └────────────────┘  └────────────────┘  └─────────────────┘
                │
       ┌────────▼────────┐
       │ External        │
       │ llama.cpp server│
       └─────────────────┘
```

## 7. Target repository structure

Expand the existing repository toward the following structure. Reuse working code and introduce compatibility modules where necessary.

```text
.
├── README.md
├── pyproject.toml
├── uv.lock                         # or the repository's existing lock format
├── .env.example
├── docs
│   ├── current-state-assessment.md
│   ├── architecture.md
│   ├── data-model.md
│   ├── openproject-integration.md
│   ├── operations.md
│   ├── testing.md
│   └── adr
│       ├── 0001-modular-agent-runtime.md
│       ├── 0002-langgraph-persistence.md
│       ├── 0003-openproject-event-input.md
│       └── 0004-mounted-repository-boundary.md
├── infra
│   ├── agent_trigger
│   │   ├── Dockerfile
│   │   └── app
│   │       ├── main.py
│   │       ├── dependencies.py
│   │       ├── schemas.py
│   │       └── routes
│   │           └── openproject_webhook.py
│   ├── models
│   ├── openproject
│   │   └── provision
│   ├── postgres
│   │   └── init
│   ├── scripts
│   │   ├── bootstrap.sh
│   │   ├── migrate.sh
│   │   ├── setup_langgraph_persistence.py
│   │   ├── provision_openproject.py
│   │   └── smoke_test.py
│   └── workspace
│       └── repositories
├── agent_core
│   ├── pyproject.toml               # retain only if package is independently managed
│   └── agent_core
│       ├── __init__.py
│       ├── config
│       │   ├── settings.py
│       │   ├── agent_definitions.py
│       │   └── logging.py
│       ├── domain
│       │   ├── enums.py
│       │   ├── identifiers.py
│       │   ├── projects.py
│       │   ├── requirements.py
│       │   ├── plans.py
│       │   ├── tasks.py
│       │   ├── feedback.py
│       │   ├── evidence.py
│       │   ├── verification.py
│       │   └── events.py
│       ├── agents
│       │   ├── base.py
│       │   ├── registry.py
│       │   ├── planning
│       │   │   └── definition.yaml
│       │   ├── coding
│       │   │   └── definition.yaml
│       │   └── verification
│       │       └── definition.yaml
│       ├── skills
│       │   ├── base
│       │   │   ├── contract.py
│       │   │   ├── context.py
│       │   │   ├── result.py
│       │   │   ├── manifest.py
│       │   │   ├── registry.py
│       │   │   └── loader.py
│       │   ├── shared
│       │   ├── planning
│       │   ├── coding
│       │   └── verification
│       ├── workflows
│       │   ├── state.py
│       │   ├── node_factory.py
│       │   ├── routing.py
│       │   ├── project_orchestrator.py
│       │   ├── planning_graph.py
│       │   ├── coding_graph.py
│       │   └── verification_graph.py
│       ├── policies
│       │   ├── approval.py
│       │   ├── repository_access.py
│       │   ├── tool_access.py
│       │   ├── transitions.py
│       │   └── side_effects.py
│       ├── ports
│       │   ├── llm.py
│       │   ├── project_management.py
│       │   ├── repository.py
│       │   ├── command_runner.py
│       │   ├── code_analysis.py
│       │   ├── graph_store.py
│       │   ├── vector_store.py
│       │   ├── domain_store.py
│       │   ├── event_bus.py
│       │   └── clock.py
│       ├── adapters
│       │   ├── llm
│       │   │   └── llama_cpp.py
│       │   ├── openproject
│       │   ├── repository
│       │   ├── command_runner
│       │   ├── tree_sitter
│       │   ├── lsp
│       │   ├── postgres
│       │   ├── neo4j
│       │   ├── weaviate
│       │   └── redis
│       ├── context
│       │   ├── capsule.py
│       │   ├── builder.py
│       │   ├── retrieval.py
│       │   ├── token_budget.py
│       │   └── redaction.py
│       ├── services
│       │   ├── project_binding_service.py
│       │   ├── webhook_event_service.py
│       │   ├── workflow_service.py
│       │   ├── feedback_service.py
│       │   ├── approval_service.py
│       │   ├── repository_analysis_service.py
│       │   ├── projection_service.py
│       │   └── reconciliation_service.py
│       ├── persistence
│       │   ├── orm
│       │   ├── repositories
│       │   ├── migrations
│       │   └── unit_of_work.py
│       ├── workers
│       │   ├── consumer.py
│       │   ├── handlers.py
│       │   └── scheduler.py
│       ├── api
│       │   ├── main.py
│       │   ├── dependencies.py
│       │   ├── schemas
│       │   └── routes
│       └── observability
│           ├── tracing.py
│           ├── metrics.py
│           ├── audit.py
│           └── correlation.py
├── tests
│   ├── unit
│   ├── contract
│   ├── integration
│   ├── workflow
│   ├── golden
│   └── e2e
└── sample_project
```

### 7.1 Compatibility with current folders

Map current folders as follows:

- `ingestion` becomes shared ingestion implementation used by planning skills. Keep a compatibility import if current code imports it directly.
- current `workflow` code moves gradually into `workflows` with tests proving equivalent behavior.
- current `services` remain application services but must not become a miscellaneous folder.
- current `adapters` are divided by external technology and must implement declared ports.
- current `skills` are migrated into the typed skill package format described below.
- `infra/agent_trigger` remains a separate thin webhook ingress process.

## 8. Runtime components

### 8.1 Agent trigger service

`infra/agent_trigger` is responsible only for ingress concerns:

1. accept webhook requests;
2. validate required headers and payload shape;
3. generate or propagate a correlation ID;
4. compute a deduplication fingerprint;
5. store the complete raw event in PostgreSQL;
6. enqueue only the persisted event ID;
7. return a quick success response after durable persistence;
8. never execute a complete agent workflow inside the request handler.

It must expose:

```text
POST /webhooks/openproject
GET  /health/live
GET  /health/ready
```

The handler must not trust an event name merely because it appears in a header. Normalize the event using both headers and payload where available.

### 8.2 Agent worker

The worker consumes persisted event IDs and:

1. acquires a processing lease;
2. loads the durable event;
3. checks whether it has already completed;
4. resolves project and repository binding;
5. classifies the event;
6. starts or resumes the relevant LangGraph thread;
7. records the outcome;
8. retries transient failures with bounded backoff;
9. sends unrecoverable events to a dead-letter state with a visible OpenProject comment when appropriate.

### 8.3 Project orchestrator

The project orchestrator is the stable top-level workflow. It delegates to planning, coding, and verification subgraphs.

```text
RECEIVE_EVENT
    ↓
LOAD_PROJECT_CONTEXT
    ↓
CLASSIFY_EVENT
    ├── requirement/task/story change ──→ PLANNING_SUBGRAPH
    ├── approved executable task ───────→ CODING_SUBGRAPH
    ├── code change ready ──────────────→ VERIFICATION_SUBGRAPH
    ├── clarification/feedback ─────────→ RESUME_WAITING_THREAD
    ├── approval/rejection ─────────────→ APPLY_APPROVAL_DECISION
    └── irrelevant/self-generated ──────→ RECORD_AND_IGNORE
```

The top-level workflow topology must be explicit in code. Conditional routing may select from predefined transitions only.

## 9. Agent definitions

Agent definitions must be configuration-driven and loaded at startup.

Example planning definition:

```yaml
name: planning_agent
workflow: planning_graph
objective: Convert project instructions and repository evidence into a validated executable plan.
allowed_skills:
  - document_ingestion
  - ambiguity_assessment
  - requirement_extraction
  - implementation_status
  - planning_decomposition
  - plan_validation
  - context_capsule
  - openproject_projection
  - neo4j_projection
  - weaviate_projection
permissions:
  repository_read: true
  repository_write: false
  run_commands: false
  update_openproject: true
limits:
  max_skill_calls: 30
  max_retries_per_skill: 2
  max_context_tokens: 20000
approval_policy: configurable
```

Create equivalent definitions for coding and verification agents.

### 9.1 Agent runtime context

Every agent and skill call receives an immutable runtime context:

```python
class AgentRuntimeContext(BaseModel):
    execution_id: UUID
    thread_id: str
    project_id: UUID
    repository_id: UUID | None
    agent_name: str
    actor: str
    correlation_id: str
    causation_id: str | None
    config_snapshot_id: UUID
    started_at: datetime
```

Never use module-level mutable variables to store active project or execution state.

## 10. Skill architecture

### 10.1 Required skill contract

```python
from abc import ABC, abstractmethod
from typing import Generic, TypeVar
from pydantic import BaseModel, ConfigDict, Field

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class SkillExecutionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    execution_id: str
    thread_id: str
    project_id: str
    repository_id: str | None = None
    agent_name: str
    correlation_id: str
    causation_id: str | None = None


class SkillResult(BaseModel, Generic[OutputT]):
    success: bool
    output: OutputT | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    retryable: bool = False


class Skill(ABC, Generic[InputT, OutputT]):
    name: str
    implementation_version: str
    contract_version: str
    input_model: type[InputT]
    output_model: type[OutputT]

    @abstractmethod
    async def execute(
        self,
        context: SkillExecutionContext,
        skill_input: InputT,
    ) -> SkillResult[OutputT]:
        raise NotImplementedError
```

### 10.2 Skill package format

Each skill is self-contained:

```text
skills/planning/requirement_extraction
├── __init__.py
├── skill.py
├── schemas.py
├── manifest.yaml
├── prompts
│   ├── system.md
│   └── extraction.md
├── validators.py
├── postprocessors.py
└── tests
    ├── test_contract.py
    ├── test_skill.py
    └── cases.json
```

### 10.3 Skill manifest

```yaml
name: requirement_extraction
contract_version: "1"
implementation_version: "1.0.0"
description: Extract normalized software requirements and traceable source evidence.
category: planning
side_effect_level: none
required_capabilities:
  - llm.structured_generation
  - document.read
allowed_agents:
  - planning_agent
  - verification_agent
input_schema: RequirementExtractionInput
output_schema: RequirementExtractionOutput
timeout_seconds: 180
max_retries: 2
tags:
  - requirements
  - document-analysis
```

### 10.4 Skill registry requirements

The registry must support:

- discovery at startup;
- uniqueness validation for name and version;
- lookup by stable skill name;
- optional explicit version lookup;
- filtering by agent and capability;
- dependency checks;
- test replacement with fakes;
- configurable implementation aliases;
- clear startup failure when a required skill is missing.

The workflow must call a generic skill node adapter rather than embedding skill implementation logic.

### 10.5 Pure and side-effecting skills

Classify every skill with one of these side-effect levels:

```text
none       read-only and safe to retry
internal   writes only internal domain data
external   changes OpenProject or another external system
repository changes mounted source files or invokes repository commands
```

External and repository side effects require an idempotency key and durable operation record.

## 11. Tool and port architecture

Tools are smaller than skills. Examples:

- read file;
- list directory;
- search text;
- get Git diff;
- apply patch;
- run configured command;
- query symbol definition;
- query references;
- create work package;
- update work package;
- add comment;
- upsert Neo4j nodes;
- insert Weaviate objects.

### 11.1 Required ports

At minimum, implement these protocols or abstract base classes:

```python
class LLMPort(Protocol):
    async def generate_text(self, request: TextGenerationRequest) -> TextGenerationResult: ...
    async def generate_structured(self, request: StructuredGenerationRequest[OutputT]) -> OutputT: ...


class ProjectManagementPort(Protocol):
    async def get_work_package(self, external_id: str) -> WorkPackageSnapshot: ...
    async def create_work_package(self, request: CreateWorkPackageRequest) -> ExternalReference: ...
    async def update_work_package(self, request: UpdateWorkPackageRequest) -> ExternalReference: ...
    async def add_comment(self, request: AddCommentRequest) -> ExternalReference: ...
    async def list_children(self, external_id: str) -> list[WorkPackageSnapshot]: ...


class RepositoryPort(Protocol):
    async def snapshot(self, repository_id: str) -> RepositorySnapshot: ...
    async def read_text(self, path: str) -> str: ...
    async def write_text(self, path: str, content: str, operation_id: str) -> FileChange: ...
    async def apply_patch(self, patch: PatchSet, operation_id: str) -> list[FileChange]: ...
    async def diff(self, base_ref: str | None = None) -> RepositoryDiff: ...


class CommandRunnerPort(Protocol):
    async def run(self, command: CommandSpec) -> CommandResult: ...


class CodeAnalysisPort(Protocol):
    async def index_repository(self, repository_id: str) -> IndexResult: ...
    async def definitions(self, symbol: SymbolQuery) -> list[SymbolLocation]: ...
    async def references(self, symbol: SymbolQuery) -> list[SymbolLocation]: ...
    async def dependency_neighborhood(self, symbol_id: str, depth: int) -> DependencySubgraph: ...
```

### 11.2 Adapter rules

- Adapters convert vendor-specific payloads into domain models at the boundary.
- Do not leak HAL+JSON OpenProject responses into skills.
- Do not leak Neo4j `Record` objects into domain code.
- Do not leak Weaviate collection objects into skills.
- Do not leak raw LLM provider response objects into workflows.
- Every adapter must have contract tests.

## 12. LLM adapter for externally hosted llama.cpp

### 12.1 Configuration

Use an OpenAI-compatible HTTP client or a small direct HTTP adapter. Do not start an LLM container.

Required settings:

```dotenv
LLM_BASE_URL=http://host.docker.internal:8080/v1
LLM_MODEL=Qwen/Qwen3-30B-A3B-Instruct-2507
LLM_API_KEY=local-not-secret
LLM_REQUEST_TIMEOUT_SECONDS=180
LLM_MAX_RETRIES=2
LLM_TEMPERATURE=0.1
LLM_MAX_OUTPUT_TOKENS=4096
LLM_CONTEXT_WINDOW=29696
LLM_STRUCTURED_OUTPUT_MODE=json_schema
```

`LLM_BASE_URL` must be configurable for Linux hosts, Windows/WSL, remote servers, and internal networks. Never hard-code `localhost`, because `localhost` inside a container refers to that container.

### 12.2 Adapter capabilities

Implement:

- health probe;
- chat completion;
- structured generation validated against a Pydantic model;
- optional streaming behind the port but not required for workflow correctness;
- retry of connection errors and selected transient status codes;
- timeout handling;
- correlation ID in logs;
- token-usage recording when the server returns usage metadata;
- request metadata without logging secrets or full sensitive prompts;
- graceful handling of malformed JSON;
- one repair attempt for schema-invalid output, followed by a typed failure.

Do not use internal `/tools` endpoints of the server. Tool execution belongs in this application.

## 13. LangGraph workflow architecture

Use LangGraph for:

- explicit state graphs;
- checkpoints;
- subgraphs;
- interruption for approval or clarification;
- retry and recovery;
- resuming by thread ID;
- state inspection.

### 13.1 Persistence

Use PostgreSQL-backed LangGraph persistence. Implement both:

- `AsyncPostgresSaver` or the appropriate asynchronous Postgres checkpointer for thread-level workflow checkpoints;
- a Postgres-backed store when cross-thread agent memory is required.

Initialization must be explicit. Add a dedicated command that calls the persistence implementation's setup/migration method. Do not rely only on an implicit setup during the first production request.

Illustrative pattern; adapt imports to the installed LangGraph version:

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

async def initialize_langgraph_persistence(database_uri: str) -> None:
    async with AsyncPostgresSaver.from_conn_string(database_uri) as checkpointer:
        await checkpointer.setup()

    async with AsyncPostgresStore.from_conn_string(database_uri) as store:
        await store.setup()
```

Pin compatible dependency versions in the lockfile and test the actual APIs used.

### 13.2 Thread identifiers

Use stable, predictable thread IDs:

```text
project:{project_uuid}:planning
project:{project_uuid}:task:{task_uuid}:coding:{attempt_number}
project:{project_uuid}:task:{task_uuid}:verification:{attempt_number}
```

A new coding attempt after verification rejection receives a new attempt number while retaining links to the prior attempt.

### 13.3 Shared workflow state

Keep state compact and store large artifacts externally.

```python
class WorkflowState(TypedDict, total=False):
    thread_id: str
    execution_id: str
    project_id: str
    repository_id: str | None
    triggering_event_id: str
    current_agent: str
    current_stage: str
    current_task_id: str | None
    requirement_ids: list[str]
    plan_id: str | None
    context_capsule_id: str | None
    skill_results: dict[str, str]       # skill name -> persisted skill-result id
    pending_approval_id: str | None
    pending_question_ids: list[str]
    retry_count: int
    warnings: list[str]
    terminal_status: str | None
```

Do not store complete repository files, large documents, embeddings, or huge LLM messages directly in checkpoint state. Store an artifact ID or snapshot ID.

### 13.4 Parent graph

The parent graph coordinates these stages:

```text
INITIALIZE
  ↓
RECONCILE_TRIGGER
  ↓
PLAN_IF_REQUIRED
  ↓
WAIT_FOR_PLAN_APPROVAL_IF_CONFIGURED
  ↓
SELECT_EXECUTABLE_TASK
  ↓
WAIT_FOR_CODE_APPROVAL_IF_CONFIGURED
  ↓
CODE
  ↓
VERIFY
  ├── accepted → COMPLETE_TASK
  ├── changes_required → CREATE_REWORK_ATTEMPT → CODE
  ├── requirement_problem → PLANNING_SUBGRAPH
  └── blocked → REPORT_BLOCKER
  ↓
FINALIZE
```

### 13.5 Approval configuration

Approval points are configurable by project and global defaults.

```yaml
approvals:
  clarification_response_required: true
  plan_projection: true
  before_repository_write: false
  before_command_execution: false
  before_task_completion: true
  verification_override_allowed: true
```

Approval is represented as durable domain data, not only a boolean in graph state.

## 14. OpenProject as the human control surface

OpenProject is not merely an output target. It is also the input channel for instructions, clarification, approval, rejection, reprioritization, and feedback.

### 14.1 Supported inbound event classes

At minimum, process the configured equivalents of:

- work package created;
- work package updated;
- work package comment added;
- internal comment added when the configured OpenProject edition exposes it;
- parent/child or relation changes where present in the payload or detected by reconciliation.

Store unknown event types and mark them ignored rather than failing the webhook endpoint.

### 14.2 Event inbox pattern

Create a durable webhook inbox table. Processing must be at-least-once safe.

Required lifecycle:

```text
RECEIVED → QUEUED → PROCESSING → COMPLETED
                            └→ RETRY_PENDING
                            └→ DEAD_LETTER
                            └→ IGNORED
```

The deduplication key should prefer a provider delivery ID. When unavailable, compute a stable hash from event type, external resource ID, event timestamp, and a canonicalized payload subset.

### 14.3 Preventing feedback loops

The agent's own OpenProject updates can generate new webhooks. Implement all of the following:

1. record each outbound operation with an operation ID;
2. add an agent marker to comments, for example an HTML comment or stable machine-readable footer that remains unobtrusive;
3. record the OpenProject actor where available;
4. compare inbound changes with pending outbound operations;
5. ignore only exact acknowledged echoes;
6. do not ignore a subsequent human edit merely because the work package was originally created by the agent.

### 14.4 Interpretation of instructions and feedback

A comment or work-package change must be classified into one of these domain commands:

```text
NEW_REQUIREMENT
CHANGE_REQUIREMENT
CLARIFICATION_RESPONSE
PLAN_FEEDBACK
APPROVE_PLAN
REJECT_PLAN
APPROVE_CODE_EXECUTION
PAUSE_AUTOMATION
RESUME_AUTOMATION
CANCEL_TASK
CHANGE_PRIORITY
CHANGE_ACCEPTANCE_CRITERIA
VERIFICATION_OVERRIDE
GENERAL_INFORMATION
IRRELEVANT
```

The classifier may use deterministic patterns first and an LLM second. The final command must be validated against the current workflow state and actor permissions configured for the project.

A plain human comment should not require a rigid command syntax. Support optional explicit commands such as `@agent approve plan`, but also classify natural-language feedback.

### 14.5 Reconciliation

Webhook payloads may be partial. After important events, fetch the current work package from OpenProject and build a normalized snapshot. Compare it with the previous stored snapshot to identify:

- changed description;
- changed acceptance criteria;
- changed status;
- changed parent;
- changed priority;
- changed assignee;
- changed relations;
- new comments;
- task deleted or no longer accessible.

### 14.6 OpenProject hierarchy

Use configurable type mappings, with these semantic defaults:

```text
OpenProject project
└── Epic
    └── Story
        └── Task
            └── optional Subtask
```

Do not assume numeric type or status IDs. Resolve them during provisioning and store mappings.

Recommended work-package content:

**Epic**

- objective;
- scope;
- business value;
- high-level constraints;
- linked source requirements.

**Story**

- user or system outcome;
- detailed description;
- acceptance criteria;
- dependencies;
- linked requirements;
- current implementation status.

**Task**

- bounded implementation action;
- files or modules likely affected;
- verification instructions;
- definition of done;
- dependencies;
- evidence links;
- agent execution status.

### 14.7 Status mapping

Create semantic internal statuses and map them to configured OpenProject statuses:

```text
DRAFT
NEEDS_CLARIFICATION
AWAITING_APPROVAL
READY
IN_PROGRESS
BLOCKED
READY_FOR_VERIFICATION
CHANGES_REQUIRED
VERIFIED
DONE
CANCELLED
```

Do not hard-code a particular OpenProject workflow. Validate transitions and post a clear comment when a configured transition is unavailable.

## 15. Mounted repository boundary

### 15.1 Mount contract

Initially, repositories are mounted into the worker container.

```yaml
services:
  agent-worker:
    volumes:
      - ./infra/workspace/repositories:/workspace/repositories
```

Each project binding stores:

```text
repository_root=/workspace/repositories/<repository_key>
```

The repository adapter must resolve every path and verify that the final resolved path remains under the configured root. Reject absolute paths and traversal outside the root.

### 15.2 Repository modes

Support:

```text
READ_ONLY
READ_WRITE
```

Planning and verification agents are read-only by default. The coding agent receives read-write access only when policy permits.

### 15.3 Git safety

The first implementation may work on the currently mounted checkout, but it must:

- detect whether it is a Git repository;
- record the starting commit and working-tree state;
- refuse to overwrite unrelated pre-existing changes unless project policy explicitly allows it;
- create a dedicated agent branch when Git is available and configured;
- never force-push;
- never merge to a protected branch;
- record the diff before and after each coding attempt;
- expose a rollback method for files changed by the current operation.

Recommended branch name:

```text
agent/<openproject-task-id>-<short-slug>-attempt-<n>
```

### 15.4 Command execution

Commands must be declared by repository configuration, not freely invented and executed without validation.

Example `agent-project.yaml` in the mounted repository:

```yaml
project:
  name: sample-project
languages:
  - python
commands:
  install: ["uv", "sync", "--frozen"]
  format_check: ["ruff", "format", "--check", "."]
  lint: ["ruff", "check", "."]
  type_check: ["mypy", "src"]
  test: ["pytest", "-q"]
write_scope:
  include:
    - "src/**"
    - "tests/**"
  exclude:
    - ".env"
    - "secrets/**"
    - ".git/**"
timeouts:
  test_seconds: 600
```

The runner must avoid shell interpolation by default. Use an argument array, a restricted working directory, a timeout, bounded output capture, and environment-variable allowlisting.

## 16. Repository understanding

Use complementary analysis methods.

### 16.1 File inventory

Collect:

- languages and file counts;
- package/module boundaries;
- build files;
- test frameworks;
- configuration files;
- documentation entry points;
- generated/vendor directories to exclude;
- Git status and recent relevant history when available.

### 16.2 Tree-sitter

Use Tree-sitter for language-aware structural extraction:

- modules;
- imports;
- classes;
- functions and methods;
- calls where statically apparent;
- decorators/annotations;
- test definitions;
- configuration declarations;
- source ranges and stable content hashes.

Use language-specific query files rather than scattering node-type checks throughout the codebase.

### 16.3 Language Server Protocol

Implement an LSP client abstraction for semantic queries:

- definition;
- references;
- document symbols;
- workspace symbols;
- hover/type information where supported;
- diagnostics.

The LSP client owns server lifecycle: initialize, initialized notification, requests, shutdown, and exit. Configure servers per language. Start with Python and add TypeScript and C++ through adapters without changing skill contracts.

Recommended initial server configuration:

```yaml
lsp:
  python:
    command: ["pyright-langserver", "--stdio"]
  typescript:
    command: ["typescript-language-server", "--stdio"]
  cpp:
    command: ["clangd"]
```

A missing language server must reduce semantic confidence and produce a warning, not crash the full planning workflow. Tree-sitter remains the structural fallback.

### 16.4 Incremental indexing

Identify changed files using Git diff or content hashes. Re-index only changed files and update affected graph relationships. A full re-index remains available as an administrative operation.

## 17. Planning agent

Implement all planning skills now. None may remain as an empty placeholder.

### 17.1 `document_ingestion_skill`

**Purpose:** Convert user-provided and OpenProject-linked source material into normalized, traceable document chunks.

**Inputs:**

- project ID;
- source descriptors;
- OpenProject descriptions/comments;
- optional mounted file paths;
- ingestion options.

**Required behavior:**

- support Markdown, plain text, source-code files, JSON, YAML, and existing extractors already present in the repository;
- preserve source location and content hash;
- split large README or design documents by semantic headings first, then token-aware windows;
- retain parent-section context;
- detect duplicates by normalized content hash;
- store raw artifact metadata in PostgreSQL;
- store retrievable chunks in Weaviate;
- emit evidence references;
- never silently discard unsupported sources.

**Output:** document IDs, chunk IDs, warnings, source inventory, and ingestion summary.

### 17.2 `ambiguity_assessment_skill`

**Purpose:** Determine whether planning can proceed safely.

Classify each ambiguity as:

```text
BLOCKING
NON_BLOCKING_ASSUMPTION
CONFLICT
MISSING_ACCEPTANCE_CRITERIA
MISSING_TECHNICAL_CONSTRAINT
MISSING_REPOSITORY_INFORMATION
```

Each item must contain:

- question;
- why it matters;
- affected requirement IDs;
- suggested options when suitable;
- safe default, if one exists;
- evidence;
- confidence.

Blocking questions are projected to OpenProject and cause a workflow interruption. Non-blocking assumptions must be recorded explicitly in the plan.

### 17.3 `requirement_extraction_skill`

**Purpose:** Create normalized, traceable requirements from documents, OpenProject content, and feedback.

Output separate:

- functional requirements;
- non-functional requirements;
- constraints;
- acceptance criteria;
- assumptions;
- exclusions;
- open questions;
- conflicts.

Every extracted item requires one or more source evidence references. Assign a stable internal ID and semantic fingerprint so an edited requirement can be reconciled rather than duplicated.

### 17.4 `implementation_status_skill`

**Purpose:** Inspect a repository that may already be partially implemented.

For each requirement or planned task, classify:

```text
COMPLETE
PARTIAL
MISSING
CONFLICTING
UNKNOWN
NOT_APPLICABLE
```

Require evidence such as:

- file and line range;
- symbol ID;
- test ID;
- configuration path;
- command result;
- Git diff or commit;
- reasoned explanation.

`COMPLETE` must not be assigned solely from a file name or LLM guess. Use code, tests, and configuration evidence.

The output must clearly separate:

- already complete;
- partially complete, including completed and missing parts;
- pending;
- implementation present but undocumented;
- code conflicting with the latest requirement;
- items that cannot be verified statically.

### 17.5 `planning_decomposition_skill`

**Purpose:** Produce epics, stories, tasks, subtasks, dependencies, and verification expectations.

Rules:

- one task should represent a bounded, reviewable change;
- preserve requirement traceability;
- do not create tasks for work proven complete unless a validation or documentation task remains;
- partial implementation creates only the missing work plus required regression checks;
- identify dependencies explicitly;
- avoid circular dependencies;
- include expected files/modules without treating them as mandatory when uncertain;
- include acceptance criteria and definition of done;
- include risk and rollback considerations for high-impact tasks;
- separate implementation from verification responsibility.

### 17.6 `plan_validation_skill`

Validate deterministically and semantically:

- every actionable requirement is covered;
- every task traces to at least one requirement or approved maintenance objective;
- no orphan story or task;
- no dependency cycle;
- no duplicate task by semantic fingerprint;
- acceptance criteria are testable;
- task scope is bounded;
- completed work is not unnecessarily recreated;
- constraints are represented;
- risks and assumptions are visible;
- verification method exists;
- plan respects configured repository and tool permissions.

Return errors, warnings, coverage metrics, and an approved normalized plan only when validation succeeds.

### 17.7 `context_capsule_skill`

**Purpose:** Build a token-bounded context package for the next skill or agent.

A capsule contains:

```python
class ContextCapsule(BaseModel):
    objective: str
    project_summary: str
    task_summary: str | None
    requirement_ids: list[str]
    requirement_text: list[str]
    acceptance_criteria: list[str]
    constraints: list[str]
    assumptions: list[str]
    relevant_files: list[FileExcerpt]
    relevant_symbols: list[SymbolSummary]
    dependency_context: list[RelationshipSummary]
    prior_decisions: list[DecisionSummary]
    prior_attempts: list[AttemptSummary]
    verification_evidence: list[EvidenceSummary]
    open_questions: list[str]
    omitted_context_summary: str
    token_budget: int
```

The builder must rank context by relevance and reserve capacity for the agent response. It must never truncate JSON or source snippets in a way that makes them syntactically misleading.

### 17.8 `openproject_projection_skill`

**Purpose:** Idempotently create or update the OpenProject representation.

Required behavior:

- resolve semantic type/status mappings;
- upsert by internal external-reference mapping, not subject text alone;
- preserve human edits unless the current instruction explicitly supersedes them;
- update descriptions, acceptance criteria, hierarchy, status, and relations;
- add concise comments for material agent decisions;
- attach or link detailed artifacts rather than posting huge comments;
- record every outbound operation and response;
- handle partial failure and retry safely.

### 17.9 `neo4j_projection_skill`

**Purpose:** Persist relationships among project, requirement, plan, task, code, test, run, and evidence entities.

Projection must be idempotent using stable IDs and `MERGE`-style semantics. Use transaction functions and parameterized Cypher.

### 17.10 `weaviate_projection_skill`

**Purpose:** Persist semantic artifacts for retrieval.

Required behavior:

- upsert by deterministic UUID;
- store content hash and version;
- support deletion/tombstoning when a source is superseded;
- apply project filtering to every search;
- use async client integration in async services;
- batch writes where appropriate;
- do not treat Weaviate as the authoritative business database.

## 18. Coding agent

Implement a complete initial coding agent, not only empty interfaces.

### 18.1 Required coding skills

#### `task_intake_skill`

Normalize the selected OpenProject task, requirement links, dependencies, policy, and current repository state. Reject tasks that are not ready or whose dependencies are incomplete.

#### `change_impact_analysis_skill`

Use repository index, Neo4j relationships, Tree-sitter, LSP, and search to identify likely affected symbols, files, tests, configuration, and callers. Return evidence and uncertainty.

#### `implementation_strategy_skill`

Produce an internal change strategy containing:

- intended behavior;
- files/symbols likely to change;
- migration concerns;
- test changes;
- compatibility risks;
- ordered steps;
- rollback approach.

This strategy is not automatically projected as a new task hierarchy unless it reveals missing planning work.

#### `code_change_skill`

Generate and apply bounded patches. Requirements:

- operate only in allowed paths;
- use current file content and symbol context;
- prefer minimal coherent changes;
- preserve project style;
- avoid unrelated refactoring;
- record each changed file and before/after hash;
- validate patch applicability;
- support rollback of the current operation;
- never claim success before checks run.

#### `test_generation_skill`

Add or update tests derived from acceptance criteria and regression risks. Avoid tests that only mirror implementation internals without validating behavior.

#### `quality_check_skill`

Run configured format, lint, type, build, and test commands. Return structured command evidence including exit code, duration, bounded stdout/stderr, and artifact location for full logs.

#### `failure_analysis_skill`

Classify failures as:

```text
IMPLEMENTATION_DEFECT
TEST_DEFECT
ENVIRONMENT_FAILURE
PRE_EXISTING_FAILURE
FLAKY_OR_NONDETERMINISTIC
REQUIREMENT_AMBIGUITY
MISSING_DEPENDENCY
TIMEOUT
UNKNOWN
```

Do not modify code based only on an unvalidated failure interpretation.

#### `coding_summary_skill`

Produce a factual summary with changed files, behavior, tests, remaining risks, unresolved warnings, and evidence IDs. This summary becomes input for verification and OpenProject updates.

### 18.2 Coding loop

```text
LOAD_TASK
  ↓
BUILD_CONTEXT_CAPSULE
  ↓
ANALYZE_IMPACT
  ↓
CREATE_STRATEGY
  ↓
OPTIONAL_WRITE_APPROVAL
  ↓
APPLY_CHANGE
  ↓
GENERATE_OR_UPDATE_TESTS
  ↓
RUN_CHECKS
  ├── success → PREPARE_VERIFICATION
  ├── retryable defect and budget remains → ANALYZE_FAILURE → APPLY_CHANGE
  ├── requirement ambiguity → RETURN_TO_PLANNING
  └── environment/blocker → REPORT_BLOCKER
```

Enforce configurable iteration limits. Persist each attempt separately.

## 19. Verification agent

The verification agent must be operational and independent from the coding decision path.

### 19.1 Required verification skills

#### `verification_scope_skill`

Derive what must be verified from requirements, acceptance criteria, task description, code diff, implementation strategy, and configured quality gates.

#### `static_review_skill`

Review the diff for:

- requirement coverage;
- correctness risks;
- error handling;
- security-sensitive behavior;
- backward compatibility;
- style and maintainability;
- unintended changes;
- missing tests;
- dead or unreachable code where detectable.

All findings require evidence.

#### `test_execution_skill`

Run the approved verification command set in a clean-enough state. Record environment and command evidence.

#### `acceptance_evaluation_skill`

Evaluate every acceptance criterion as:

```text
PASS
FAIL
PARTIAL
NOT_TESTED
NOT_VERIFIABLE
NOT_APPLICABLE
```

A task cannot be marked verified while a mandatory criterion is `FAIL`, `PARTIAL`, `NOT_TESTED`, or `NOT_VERIFIABLE`, unless a configured authorized human override is recorded.

#### `regression_assessment_skill`

Use impact analysis and test evidence to judge whether affected components have sufficient regression coverage.

#### `verification_decision_skill`

Return exactly one outcome:

```text
ACCEPTED
CHANGES_REQUIRED
BLOCKED
REQUIREMENT_CHANGE_REQUIRED
HUMAN_REVIEW_REQUIRED
```

Include findings grouped by severity, required corrections, optional improvements, evidence, and confidence.

#### `verification_projection_skill`

Update the internal verification record and OpenProject. Do not erase prior attempt findings.

### 19.2 Independence rule

The coding agent's summary is evidence, not truth. The verification agent must inspect the actual repository state, diff, and test results.

## 20. Context and memory

### 20.1 Four distinct persistence concepts

Do not combine these:

1. **LangGraph checkpoints:** current execution position and compact thread state.
2. **PostgreSQL domain data:** authoritative projects, requirements, plans, tasks, attempts, approvals, events, and evidence metadata.
3. **Neo4j graph data:** relationships and dependency navigation.
4. **Weaviate semantic data:** text chunks, summaries, decisions, and retrieval-oriented representations.

### 20.2 Context retrieval order

For a task capsule:

1. load authoritative task and requirement records from PostgreSQL;
2. load repository snapshot and direct linked code evidence;
3. query Neo4j for dependency neighborhood;
4. query Weaviate using project and task filters;
5. include recent relevant decisions and failed attempts;
6. deduplicate and rank;
7. enforce token budget;
8. record why each item was included.

### 20.3 Memory write policy

Do not store every model message as long-term memory. Persist only useful durable knowledge, for example:

- approved architecture decisions;
- clarified requirements;
- verified implementation summaries;
- recurring project constraints;
- validated troubleshooting knowledge;
- human feedback that should guide later tasks.

Draft reasoning and unverified model claims are not durable knowledge.

## 21. PostgreSQL domain schema

Use SQLAlchemy 2.x style models and Alembic migrations. Prefer UUID primary keys internally. Store external IDs separately. All mutable tables require `created_at`, `updated_at`, and an optimistic concurrency field where relevant.

### 21.1 `projects`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | Internal project ID |
| name | text | Display name |
| status | enum/text | ACTIVE, PAUSED, ARCHIVED |
| openproject_project_id | text unique nullable | External project/workspace ID |
| approval_policy | jsonb | Project override |
| agent_config | jsonb | Limits and enabled capabilities |
| created_at | timestamptz | |
| updated_at | timestamptz | |

### 21.2 `repositories`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| repository_key | text | Stable key |
| mount_path | text | Container path |
| access_mode | text | READ_ONLY or READ_WRITE |
| default_branch | text nullable | |
| config_path | text nullable | `agent-project.yaml` |
| language_summary | jsonb | |
| is_active | boolean | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

Unique: `(project_id, repository_key)`.

### 21.3 `webhook_inbox_events`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | Queue payload references this |
| provider | text | OPENPROJECT |
| delivery_id | text nullable | |
| dedupe_key | text unique | |
| event_type | text | Normalized event |
| external_resource_id | text nullable | |
| headers | jsonb | Redacted |
| payload | jsonb | Raw payload |
| status | text | Inbox lifecycle |
| attempt_count | integer | |
| next_attempt_at | timestamptz nullable | |
| lease_owner | text nullable | |
| lease_expires_at | timestamptz nullable | |
| correlation_id | text | |
| received_at | timestamptz | |
| completed_at | timestamptz nullable | |
| last_error | jsonb nullable | |

### 21.4 `domain_events`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID nullable | |
| aggregate_type | text | |
| aggregate_id | UUID/text | |
| event_type | text | |
| schema_version | integer | |
| payload | jsonb | |
| correlation_id | text | |
| causation_id | text nullable | |
| producer | text | |
| occurred_at | timestamptz | |

### 21.5 `agent_executions`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| agent_name | text | |
| thread_id | text | |
| trigger_event_id | UUID nullable | |
| parent_execution_id | UUID nullable | |
| attempt_number | integer | |
| status | text | CREATED, RUNNING, WAITING, SUCCEEDED, FAILED, CANCELLED |
| config_snapshot | jsonb | |
| started_at | timestamptz nullable | |
| ended_at | timestamptz nullable | |
| error_summary | jsonb nullable | |

Index: `(thread_id, started_at desc)`.

### 21.6 `skill_runs`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| execution_id | UUID FK | |
| skill_name | text | |
| contract_version | text | |
| implementation_version | text | |
| sequence_number | integer | |
| input_artifact_id | UUID nullable | Large input reference |
| output_artifact_id | UUID nullable | |
| status | text | |
| confidence | numeric nullable | |
| started_at | timestamptz | |
| ended_at | timestamptz nullable | |
| warnings | jsonb | |
| errors | jsonb | |
| token_usage | jsonb nullable | |

### 21.7 `artifacts`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| artifact_type | text | DOCUMENT, PLAN, LOG, DIFF, REPORT, CONTEXT_CAPSULE, etc. |
| storage_backend | text | POSTGRES, FILESYSTEM, OBJECT_STORE |
| storage_uri | text nullable | |
| content_json | jsonb nullable | Small structured content only |
| content_hash | text | |
| media_type | text | |
| size_bytes | bigint | |
| created_by_execution_id | UUID nullable | |
| created_at | timestamptz | |

### 21.8 `source_documents` and `document_chunks`

`source_documents` stores source identity, revision, origin, hash, and artifact link. `document_chunks` stores section path, ordinal, token estimate, source range, hash, and Weaviate object ID.

### 21.9 `requirements`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| requirement_key | text | Human-readable stable key |
| kind | text | FUNCTIONAL, NON_FUNCTIONAL, CONSTRAINT, etc. |
| title | text | |
| description | text | |
| status | text | ACTIVE, SUPERSEDED, REMOVED |
| priority | text nullable | |
| semantic_fingerprint | text | Reconciliation aid |
| version | integer | |
| supersedes_id | UUID nullable | |
| metadata | jsonb | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

Unique: `(project_id, requirement_key, version)`.

### 21.10 `requirement_evidence`

Maps requirements to source document ranges, OpenProject comments, repository symbols, tests, or other artifacts. Include evidence type, locator, excerpt hash, confidence, and originating skill run.

### 21.11 `ambiguities`

Store classification, question, rationale, options, default assumption, status, OpenProject reference, response, responder, and resolved timestamp.

### 21.12 `plans`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| version | integer | |
| status | text | DRAFT, VALIDATED, AWAITING_APPROVAL, APPROVED, SUPERSEDED |
| coverage_summary | jsonb | |
| validation_summary | jsonb | |
| created_by_execution_id | UUID | |
| approved_by | text nullable | |
| approved_at | timestamptz nullable | |
| created_at | timestamptz | |

### 21.13 `plan_items`

One table can represent epic, story, task, and subtask using `item_type` and `parent_id`.

Required fields:

- ID;
- plan ID;
- parent ID;
- item type;
- stable item key;
- title;
- description;
- acceptance criteria JSON;
- definition of done JSON;
- implementation status;
- execution status;
- priority;
- estimated complexity;
- sequence;
- OpenProject work-package ID;
- semantic fingerprint;
- metadata.

### 21.14 `plan_item_requirements`

Many-to-many traceability table with coverage type and notes.

### 21.15 `plan_item_dependencies`

Store predecessor, successor, dependency type, source, and validation status. Add a unique constraint preventing duplicate edges.

### 21.16 `repository_snapshots`

Store repository ID, commit SHA, branch, dirty status, file-manifest artifact, index version, content hash, and timestamp.

### 21.17 `code_symbols`

PostgreSQL stores authoritative symbol metadata and Neo4j stores relationships.

Fields:

- repository ID;
- snapshot ID;
- symbol stable ID;
- language;
- kind;
- qualified name;
- file path;
- start/end position;
- signature;
- content hash;
- parser source;
- metadata.

### 21.18 `implementation_assessments`

Store requirement or task ID, snapshot ID, classification, completed parts, missing parts, conflict description, confidence, and originating skill run.

### 21.19 `coding_attempts`

Store task ID, attempt number, starting snapshot, ending snapshot, branch, status, strategy artifact, diff artifact, summary artifact, and execution ID.

Unique: `(plan_item_id, attempt_number)`.

### 21.20 `command_runs`

Store attempt ID, command kind, argument list, working directory, environment fingerprint, start/end time, exit code, timeout flag, stdout/stderr artifact IDs, and status.

### 21.21 `verification_runs`

Store coding attempt, verifier execution, outcome, scope artifact, report artifact, started/ended time, and human override details.

### 21.22 `acceptance_results`

Store verification run, requirement or criterion key, result, evidence IDs, explanation, and severity.

### 21.23 `approvals`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| approval_type | text | PLAN, REPOSITORY_WRITE, TASK_COMPLETION, OVERRIDE |
| subject_type | text | |
| subject_id | text | |
| status | text | PENDING, APPROVED, REJECTED, EXPIRED, CANCELLED |
| requested_by_execution_id | UUID | |
| external_work_package_id | text nullable | |
| request_comment_id | text nullable | |
| decided_by | text nullable | |
| decision_comment_id | text nullable | |
| decision_reason | text nullable | |
| requested_at | timestamptz | |
| decided_at | timestamptz nullable | |

### 21.24 `human_feedback`

Store source event/comment, classified command, target entity, raw text, normalized instruction, status, applied execution, and resolution.

### 21.25 `external_entity_mappings`

Map internal entity type/ID to provider, external ID, external URL, last synchronized revision, and last snapshot hash.

### 21.26 `side_effect_operations`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | Idempotency key |
| operation_type | text | |
| target_system | text | |
| target_reference | text | |
| request_hash | text | |
| status | text | STARTED, SUCCEEDED, FAILED, UNKNOWN |
| response_reference | jsonb nullable | |
| execution_id | UUID | |
| created_at | timestamptz | |
| completed_at | timestamptz nullable | |

## 22. Neo4j schema

### 22.1 Node labels

Use stable IDs shared with PostgreSQL where applicable.

```text
Project
Repository
Snapshot
Document
DocumentChunk
Requirement
Constraint
Plan
Epic
Story
Task
CodeFile
CodeSymbol
TestCase
AgentExecution
CodingAttempt
VerificationRun
Evidence
Decision
```

### 22.2 Core relationships

```text
(Project)-[:HAS_REPOSITORY]->(Repository)
(Repository)-[:HAS_SNAPSHOT]->(Snapshot)
(Project)-[:HAS_REQUIREMENT]->(Requirement)
(Document)-[:HAS_CHUNK]->(DocumentChunk)
(DocumentChunk)-[:SUPPORTS]->(Requirement)
(Requirement)-[:CONSTRAINED_BY]->(Constraint)
(Plan)-[:CONTAINS]->(Epic)
(Epic)-[:CONTAINS]->(Story)
(Story)-[:CONTAINS]->(Task)
(Task)-[:DEPENDS_ON]->(Task)
(Task)-[:IMPLEMENTS]->(Requirement)
(Task)-[:MODIFIES]->(CodeFile)
(Task)-[:TOUCHES_SYMBOL]->(CodeSymbol)
(CodeFile)-[:DECLARES]->(CodeSymbol)
(CodeFile)-[:IMPORTS]->(CodeFile)
(CodeSymbol)-[:CALLS]->(CodeSymbol)
(CodeSymbol)-[:REFERENCES]->(CodeSymbol)
(CodeSymbol)-[:EXTENDS]->(CodeSymbol)
(CodeSymbol)-[:IMPLEMENTS_INTERFACE]->(CodeSymbol)
(TestCase)-[:TESTS]->(CodeSymbol)
(TestCase)-[:VERIFIES]->(Requirement)
(CodingAttempt)-[:FOR_TASK]->(Task)
(CodingAttempt)-[:PRODUCED]->(Evidence)
(VerificationRun)-[:VERIFIES_ATTEMPT]->(CodingAttempt)
(VerificationRun)-[:PRODUCED]->(Evidence)
(Decision)-[:AFFECTS]->(Requirement|Task|CodeSymbol)
(AgentExecution)-[:USED_EVIDENCE]->(Evidence)
```

### 22.3 Constraints and indexes

Create uniqueness constraints for `id` on principal labels. Create indexes for:

- `Requirement.project_id`;
- `Task.project_id`;
- `CodeSymbol.repository_id`;
- `CodeSymbol.qualified_name`;
- `CodeFile.path` plus repository ID;
- `Evidence.project_id`;
- snapshot IDs.

### 22.4 Projection rules

- PostgreSQL remains authoritative for entity lifecycle.
- Neo4j projection is rebuildable.
- Every projected node includes `id`, `project_id`, `updated_at`, and `source_version` where applicable.
- Remove or mark stale relationships when a new repository snapshot invalidates them.
- Use parameterized queries and transaction functions.
- Projection failures must not corrupt the domain transaction; use an outbox/retry approach.

## 23. Weaviate collections

Use explicit collections with deterministic IDs and project filtering. Do not rely on automatic schema creation.

### 23.1 `ProjectDocumentChunk`

Properties:

```text
project_id                 text/filterable
repository_id              text/filterable nullable
document_id                text/filterable
chunk_id                   text/filterable
source_type                text/filterable
source_uri                 text
section_path               text
content                    text/vectorized
content_hash               text/filterable
revision                    int
language                   text/filterable nullable
token_count                int
created_at                 date
is_active                  boolean/filterable
```

### 23.2 `RequirementKnowledge`

```text
project_id
requirement_id
requirement_key
kind
title
content
acceptance_criteria
constraints
status
version
content_hash
updated_at
```

### 23.3 `CodeKnowledge`

Store summaries rather than blindly embedding every entire file.

```text
project_id
repository_id
snapshot_id
symbol_id
file_path
language
symbol_kind
qualified_name
signature
summary
selected_source_excerpt
content_hash
updated_at
```

### 23.4 `DecisionKnowledge`

```text
project_id
decision_id
decision_type
title
context
decision
rationale
consequences
status
affected_entity_ids
approved_by
approved_at
content_hash
```

### 23.5 `ExecutionKnowledge`

Only verified or intentionally retained summaries:

```text
project_id
execution_id
task_id
agent_name
outcome
summary
problems
resolution
verification_status
evidence_ids
created_at
```

### 23.6 Retrieval requirements

Every query must include `project_id`. Add repository and active-version filters where applicable. Retrieval returns object IDs and scores, then the context service resolves authoritative records and access policy before inclusion.

## 24. Domain events and outbox

Use domain events to decouple core state changes from projections.

Example envelope:

```python
class DomainEvent(BaseModel):
    id: UUID
    event_type: str
    schema_version: int
    project_id: UUID | None
    aggregate_type: str
    aggregate_id: str
    correlation_id: str
    causation_id: str | None
    producer: str
    occurred_at: datetime
    payload: dict[str, Any]
```

Core events include:

```text
OpenProjectEventReceived
ProjectBindingChanged
DocumentIngested
RequirementsExtracted
AmbiguityDetected
ClarificationRequested
ClarificationResolved
ImplementationAssessed
PlanCreated
PlanValidated
PlanApprovalRequested
PlanApproved
PlanRejected
PlanProjected
TaskReady
CodingAttemptStarted
RepositoryChanged
QualityChecksCompleted
CodingAttemptCompleted
VerificationStarted
VerificationCompleted
TaskAccepted
TaskChangesRequired
TaskBlocked
ProjectPaused
ProjectResumed
```

Use a transactional outbox so domain updates and event publication cannot diverge.

## 25. APIs

The internal FastAPI application should expose administrative and inspection endpoints. OpenProject remains the main human interface.

### 25.1 Health

```text
GET /health/live
GET /health/ready
```

Readiness should check configured required dependencies without performing expensive operations.

### 25.2 Projects and repository bindings

```text
POST /api/v1/projects/bind
GET  /api/v1/projects/{project_id}
PATCH /api/v1/projects/{project_id}/config
POST /api/v1/projects/{project_id}/pause
POST /api/v1/projects/{project_id}/resume
POST /api/v1/projects/{project_id}/reconcile
```

Example bind request:

```json
{
  "openproject_project_id": "12",
  "name": "coding-agent-demo",
  "repository": {
    "repository_key": "sample-project",
    "mount_path": "/workspace/repositories/sample-project",
    "access_mode": "READ_WRITE"
  }
}
```

### 25.3 Workflow inspection

```text
GET  /api/v1/executions/{execution_id}
GET  /api/v1/threads/{thread_id}/state
POST /api/v1/threads/{thread_id}/resume
POST /api/v1/threads/{thread_id}/cancel
```

Resume/cancel endpoints require an explicit reason and must create an audit event.

### 25.4 Repository analysis

```text
POST /api/v1/projects/{project_id}/repositories/{repository_id}/index
GET  /api/v1/projects/{project_id}/repositories/{repository_id}/snapshots
GET  /api/v1/projects/{project_id}/symbols/{symbol_id}
```

### 25.5 Debug operations

Development-only endpoints may replay a stored webhook event or run a skill with fixture input. They must be disabled by default outside development.

## 26. Configuration

Use Pydantic Settings with environment-variable support and validation.

Minimum `.env.example`:

```dotenv
APP_ENV=development
APP_LOG_LEVEL=INFO
APP_HOST=0.0.0.0
APP_PORT=8090

POSTGRES_DSN=postgresql+psycopg://coding_agent:change-me@postgres:5432/coding_agent
LANGGRAPH_POSTGRES_DSN=postgresql://coding_agent:change-me@postgres:5432/coding_agent
REDIS_URL=redis://redis:6379/0

OPENPROJECT_BASE_URL=http://openproject:80
OPENPROJECT_API_TOKEN=change-me
OPENPROJECT_WEBHOOK_SECRET=
OPENPROJECT_AGENT_USER_ID=
OPENPROJECT_REQUEST_TIMEOUT_SECONDS=30

NEO4J_URI=bolt://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=change-me
NEO4J_DATABASE=neo4j

WEAVIATE_HTTP_HOST=weaviate
WEAVIATE_HTTP_PORT=8080
WEAVIATE_GRPC_HOST=weaviate
WEAVIATE_GRPC_PORT=50051
WEAVIATE_SECURE=false

LLM_BASE_URL=http://host.docker.internal:8080/v1
LLM_MODEL=Qwen/Qwen3-30B-A3B-Instruct-2507
LLM_API_KEY=local-not-secret
LLM_REQUEST_TIMEOUT_SECONDS=180
LLM_MAX_RETRIES=2
LLM_CONTEXT_WINDOW=29696
LLM_MAX_OUTPUT_TOKENS=4096
LLM_TEMPERATURE=0.1

REPOSITORY_MOUNT_ROOT=/workspace/repositories
DEFAULT_REPOSITORY_ACCESS_MODE=READ_ONLY
COMMAND_OUTPUT_LIMIT_BYTES=1048576
DEFAULT_COMMAND_TIMEOUT_SECONDS=600

APPROVAL_PLAN_REQUIRED=true
APPROVAL_REPOSITORY_WRITE_REQUIRED=false
APPROVAL_TASK_COMPLETION_REQUIRED=true

WORKER_CONCURRENCY=2
WORKER_LEASE_SECONDS=300
WORKER_MAX_EVENT_ATTEMPTS=5
```

Never commit secrets. Redact secrets from logs, database header storage, and exception payloads.

## 27. Docker Compose expectations

Extend the existing Compose setup rather than replacing it blindly.

Expected application services:

```text
agent-trigger
agent-worker
optional agent-api
postgres
redis
neo4j
weaviate
openproject and its existing dependencies
```

There must be **no llama.cpp model service** in this Compose project.

The worker receives the mounted repository volume. The trigger service does not need repository access.

Add startup/health dependencies carefully. Do not assume `depends_on` alone means a service is ready. Provide health checks and retry connections at application startup.

Include an `extra_hosts` option for Linux environments when `host.docker.internal` is used:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Keep network configuration portable. Do not embed one machine's fixed Docker subnet into application logic.

## 28. OpenProject provisioning

Extend `infra/openproject/provision` to idempotently configure or document:

- required work-package types;
- semantic status mappings;
- priorities;
- project modules;
- custom fields where necessary;
- webhook URL and enabled events;
- agent API user/token instructions;
- required permissions;
- sample project binding.

Provisioning must discover existing entities before creating them. Store discovered numeric IDs in application mappings; do not rely on assumed IDs.

Recommended custom fields only when necessary:

```text
Agent Entity ID
Agent Execution Status
Verification Status
Repository Key
Requirement Keys
```

Avoid creating many custom fields for data that belongs in the work-package description or internal database.

## 29. Reliability and idempotency

### 29.1 Required idempotency boundaries

- webhook receipt;
- domain-command application;
- OpenProject create/update/comment;
- repository patch application;
- Neo4j projection;
- Weaviate upsert;
- workflow resume;
- task completion.

### 29.2 Retry classification

```text
TRANSIENT_NETWORK
RATE_OR_CAPACITY
DEPENDENCY_UNAVAILABLE
OPTIMISTIC_CONCURRENCY_CONFLICT
INVALID_INPUT
POLICY_DENIED
AUTHENTICATION_FAILURE
PERMANENT_EXTERNAL_ERROR
UNKNOWN
```

Retry only safe transient categories. Do not retry validation or policy failures automatically.

### 29.3 OpenProject concurrency

Respect the API's current resource representation and concurrency controls when present. On update conflict:

1. refetch the work package;
2. reconcile human changes;
3. recompute the intended patch;
4. retry only if the result remains semantically valid.

### 29.4 Recovery after unknown side-effect result

When a request times out after it may have reached the provider, mark the operation `UNKNOWN`, query the target using the idempotency marker or external mapping, and resolve it before repeating.

## 30. Security and safety boundaries

Implement these controls even for the MVP because they protect the core concept:

- path containment under the mounted repository root;
- repository write allowlist and denylist;
- argument-array command execution;
- command allowlist from repository configuration;
- execution timeout;
- bounded output capture;
- secret redaction;
- no logging of authorization tokens;
- no use of repository `.env` values unless explicitly allowed;
- planning and verification read-only repository access by default;
- external side-effect policy checks;
- approval enforcement before configured transitions;
- no destructive Git commands by default;
- no deletion outside the current task's tracked changes;
- no OpenProject update from unvalidated LLM JSON;
- webhook secret verification when configured;
- audit trail for manual overrides.

## 31. Observability

### 31.1 Structured logs

Every log record should include where available:

```text
correlation_id
causation_id
project_id
repository_id
thread_id
execution_id
skill_run_id
webhook_event_id
openproject_work_package_id
agent_name
workflow_stage
```

### 31.2 Metrics

Expose or record at minimum:

- webhook events received by type/status;
- queue depth;
- event processing duration;
- active and waiting workflows;
- skill duration and success rate;
- LLM request duration and invalid-structure count;
- command duration and failure count;
- OpenProject API failures;
- repository indexing duration;
- context-capsule token estimate;
- verification outcomes;
- retries and dead-letter events.

### 31.3 Audit

Audit records must capture:

- human approval and override;
- repository write;
- command execution;
- external-system mutation;
- workflow cancellation;
- project pause/resume;
- configuration change.

## 32. Testing strategy

### 32.1 Unit tests

Test:

- Pydantic validation;
- path policies;
- event classification;
- status mapping;
- dependency-cycle detection;
- context token budgeting;
- semantic fingerprint calculation;
- feedback classification fallbacks;
- retry classification;
- approval policies.

### 32.2 Contract tests

Every skill must have tests proving:

- input schema;
- output schema;
- manifest compatibility;
- failure behavior;
- no undeclared side effects.

Every adapter must have tests against recorded or local service responses.

### 32.3 Integration tests

Use test containers or the repository's Compose stack for:

- PostgreSQL repositories and Alembic migrations;
- LangGraph checkpoint setup, save, restart, and resume;
- Redis enqueue/consume;
- Neo4j projection and queries;
- Weaviate collection provisioning/upsert/search;
- OpenProject client operations against a test instance where practical;
- mounted repository path enforcement;
- LSP lifecycle using a small fixture repository.

### 32.4 Workflow tests

Compile graphs with fake skills and adapters. Test:

1. new project planning;
2. blocking ambiguity interruption and resume;
3. configurable plan approval;
4. partially implemented repository;
5. human task edit causing replanning;
6. coding success;
7. coding failure and bounded retry;
8. verification changes required and new coding attempt;
9. task completion approval;
10. process restart while waiting;
11. duplicate webhook event;
12. self-generated OpenProject echo;
13. project pause and resume.

### 32.5 Golden datasets

Create reviewed fixture cases for:

- requirement extraction;
- ambiguity assessment;
- implementation-status classification;
- plan decomposition;
- acceptance evaluation;
- failure classification.

Store expected structured outputs or invariant assertions. Do not assert exact prose where semantic fields are sufficient.

### 32.6 End-to-end scenario

The required E2E fixture is `sample_project`.

Scenario:

1. bind an OpenProject project to the mounted `sample_project`;
2. create or update a story describing a feature;
3. deliver the webhook;
4. extract requirements;
5. assess current implementation;
6. create/update epic, story, and tasks;
7. approve the plan when configured;
8. execute one task on an agent branch;
9. run tests;
10. verify acceptance criteria;
11. update the OpenProject task with evidence;
12. restart worker during a waiting stage and prove resume works;
13. redeliver a webhook and prove no duplicate work package or patch is created.

## 33. Coding standards

Use:

- Python 3.11 or newer, aligned with the existing environment;
- full type annotations on public APIs;
- Pydantic v2 models;
- SQLAlchemy 2.x patterns;
- Alembic migrations;
- async I/O for network services;
- dependency injection through constructors or FastAPI dependencies;
- small focused modules;
- docstrings for public contracts and non-obvious policy decisions;
- Ruff for linting and formatting unless an existing tool is already established;
- MyPy or Pyright for type checking;
- Pytest for tests.

Do not introduce a large framework merely to implement dependency injection or event dispatch. Keep the implementation explicit.

## 34. Implementation phases for Codex

Codex must implement in these phases, keeping the repository runnable after each phase.

### Phase 0: Assessment and safety net

Deliver:

- current-state assessment;
- baseline test run;
- architecture decision records;
- updated root README plan;
- identified migration map;
- no destructive refactor.

Acceptance:

- current behavior is documented;
- existing tests run or failures are recorded;
- target package imports compile.

### Phase 1: Domain foundation and configuration

Deliver:

- domain models and enums;
- settings;
- ports;
- unit of work;
- initial PostgreSQL models and migrations;
- event envelope;
- artifact storage abstraction.

Acceptance:

- migration upgrades from a clean database;
- domain package imports no vendor adapters;
- unit tests pass.

### Phase 2: Skill and agent runtime

Deliver:

- skill contract;
- manifests and loader;
- skill registry;
- agent definitions and registry;
- generic LangGraph skill-node adapter;
- fake skill test harness.

Acceptance:

- required skills are discovered;
- duplicate/missing manifests fail clearly;
- workflows can execute with fake skills.

### Phase 3: Persistence and event ingestion

Deliver:

- LangGraph Postgres setup command;
- checkpoint integration;
- store integration where needed;
- webhook inbox;
- Redis queue;
- worker lease/retry logic;
- trigger service refactor.

Acceptance:

- webhook returns after persistence;
- duplicate delivery is safe;
- a waiting graph resumes after process restart.

### Phase 4: OpenProject adapter and feedback loop

Deliver:

- normalized OpenProject client;
- reconciliation snapshots;
- semantic type/status mapping;
- outbound idempotency;
- feedback classification;
- approval records and resume logic;
- provisioning updates.

Acceptance:

- agent-created work package is not duplicated;
- a human comment resumes the correct thread;
- agent echo webhooks are ignored without ignoring later human edits.

### Phase 5: Repository analysis

Deliver:

- mounted repository adapter;
- path/write policies;
- Git snapshot/diff support;
- Tree-sitter indexing;
- LSP client abstraction and Python adapter;
- code-symbol persistence;
- Neo4j code projection;
- incremental re-indexing.

Acceptance:

- sample project symbols and relationships are queryable;
- traversal outside the mount is rejected;
- missing LSP produces a warning and fallback.

### Phase 6: Complete planning agent

Deliver all ten planning skills and planning graph.

Acceptance:

- large README ingestion works;
- requirements have evidence;
- blocking ambiguities interrupt;
- existing implementation is classified with evidence;
- validated plan has no orphan/cyclic tasks;
- OpenProject projection is idempotent;
- Neo4j and Weaviate projections are queryable.

### Phase 7: Complete coding agent

Deliver all coding skills, safe command runner, branch/diff handling, retry loop, and OpenProject progress updates.

Acceptance:

- an approved sample task changes only allowed paths;
- quality commands run and persist evidence;
- failed checks cannot produce a success state;
- attempt rollback is available.

### Phase 8: Complete verification agent

Deliver all verification skills, acceptance matrix, decision logic, rework flow, and task-completion projection.

Acceptance:

- verification independently reads actual diff and test evidence;
- failed mandatory criterion blocks completion;
- changes-required starts a linked new attempt;
- configured human override is audited.

### Phase 9: E2E hardening and documentation

Deliver:

- complete E2E scenario;
- smoke-test script;
- operations guide;
- troubleshooting guide;
- architecture diagrams;
- API documentation;
- example configuration;
- sample OpenProject workflow instructions.

Acceptance:

- clean-clone setup is documented;
- all services except external llama.cpp start through the existing infrastructure setup;
- smoke test verifies dependencies and sample flow;
- all test suites pass or environment-dependent exclusions are explicitly documented.

## 35. Definition of done

The system is complete only when all of the following are true:

- planning, coding, and verification workflows are implemented;
- all listed planning skills are functional;
- coding and verification skills are functional;
- skills use typed contracts and registry resolution;
- vendor integrations are behind ports;
- PostgreSQL migrations exist;
- LangGraph checkpoints survive restart;
- OpenProject instructions and comments can resume or alter workflows;
- configurable approvals are enforced;
- duplicate webhooks and outbound operations are safe;
- mounted repository boundaries are enforced;
- existing implementation status affects planning;
- requirement-to-code-to-test traceability exists;
- Neo4j and Weaviate projections are rebuildable;
- tests include unit, contract, integration, workflow, golden, and E2E coverage;
- documentation explains setup, configuration, operation, and recovery;
- no LLM hosting is added to the repository.

## 36. Required example flows

### 36.1 New project

```text
Story created in OpenProject
→ webhook persisted
→ project orchestrator starts planning
→ requirements extracted
→ ambiguity assessment passes
→ repository inspected
→ plan decomposed and validated
→ approval requested if configured
→ epics/stories/tasks projected
→ first ready task selected
→ coding attempt
→ verification
→ task completion approval if configured
→ task marked done
```

### 36.2 Existing half-complete project

```text
Story or planning instruction received
→ requirements extracted
→ repository indexed
→ implementation status compares requirement evidence with code/tests
→ complete work is linked and not recreated
→ partial work produces only missing tasks
→ plan projected with status/evidence
→ pending task enters coding flow
```

### 36.3 Human feedback during planning

```text
Plan awaiting approval
→ human edits a story and comments with feedback
→ webhook reconciles current work package
→ feedback classified as CHANGE_REQUIREMENT / PLAN_FEEDBACK
→ old plan version remains stored
→ requirements versioned
→ planning graph resumes and creates new plan version
→ validation reruns
→ updated approval requested
```

### 36.4 Verification rejection

```text
Coding checks pass
→ verification finds uncovered mandatory criterion
→ verification outcome CHANGES_REQUIRED
→ OpenProject receives evidence and required changes
→ new coding attempt created
→ context capsule includes previous failure
→ code updated and retested
→ verification reruns
```

## 37. Initial bootstrap commands

Codex must adapt these commands to the repository's chosen package manager and Compose filenames.

```bash
cp .env.example .env

docker compose up -d postgres redis neo4j weaviate openproject

python -m agent_core.persistence.migrations upgrade
python infra/scripts/setup_langgraph_persistence.py
python infra/scripts/provision_openproject.py

docker compose up -d agent-trigger agent-worker
python infra/scripts/smoke_test.py
```

Document how to configure `LLM_BASE_URL` when the LLM server runs:

- on the Docker host;
- on another LAN machine;
- in WSL;
- on an internal DNS name.

## 38. Codex working rules

While implementing:

1. inspect before modifying;
2. keep commits or changes logically grouped;
3. do not replace working integration code without tests proving parity;
4. run focused tests after each module;
5. run the full relevant suite at the end of each phase;
6. update documentation with implementation changes;
7. add migrations rather than editing already-applied database state manually;
8. keep prompts versioned inside skill packages;
9. store large model outputs as artifacts, not checkpoint blobs;
10. do not mark a phase complete with placeholder methods, `pass`, or unimplemented production branches;
11. clearly document environmental limitations;
12. prefer a smaller working vertical slice over broad disconnected stubs, while still completing every phase in this specification.

## 39. Official technical references

Use current official documentation when an API differs from examples in this README:

- LangGraph persistence: <https://docs.langchain.com/oss/python/langgraph/persistence>
- LangGraph memory and database setup: <https://docs.langchain.com/oss/python/langgraph/add-memory>
- OpenProject API and webhooks: <https://www.openproject.org/docs/system-admin-guide/api-and-webhooks/>
- OpenProject API v3: <https://www.openproject.org/docs/api/>
- OpenProject work packages API: <https://www.openproject.org/docs/api/endpoints/work-packages/>
- llama.cpp server: <https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md>
- Weaviate Python client: <https://docs.weaviate.io/weaviate/client-libraries/python>
- Weaviate async client: <https://docs.weaviate.io/weaviate/client-libraries/python/async>
- Neo4j Python driver: <https://neo4j.com/docs/python-manual/current/>
- Tree-sitter parser guide: <https://tree-sitter.github.io/tree-sitter/using-parsers/>
- Language Server Protocol: <https://microsoft.github.io/language-server-protocol/>

When documentation and this file conflict on exact library syntax, preserve the architecture and contracts described here while adapting the adapter-level code to the installed supported API. Record material deviations in an ADR.
