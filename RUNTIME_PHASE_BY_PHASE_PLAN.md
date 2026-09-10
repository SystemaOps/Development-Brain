# Software Development Brain — Runtime and Integration Phase Plan

> Detailed implementation plan for the coding agent after completion of internal Brain Phases 1–20.

---

## 1. Starting Point

The existing repository already implements the internal Brain layers:

```text
domain
ports
application services
adapters
persistence
code intelligence
knowledge graph
semantic retrieval
context construction
planning
execution contracts
verification internals
```

The repository is still a library. There is currently no complete application runtime:

```text
FastAPI application
runtime composition root
worker executable
scheduler/reconciler executable
CLI
project scripts
Brain Docker application image
runtime capability registry
human-observation projection pipeline
full reference integration environment
```

This plan starts from that point.

Do **not** reimplement Phases 1–20 unless the runtime work exposes a genuine contract gap.

---

## 2. Global Rules for the Coding Agent

### 2.1 Inspect Before Changing

Before each task:

1. search the repository for equivalent existing functionality;
2. inspect current contracts and implementations;
3. inspect tests and callers;
4. extend existing abstractions where possible;
5. avoid parallel duplicate abstractions.

### 2.2 Preserve Layering

Runtime dependency direction:

```text
API / Worker / CLI / Scheduler
        ↓
Application Services
        ↓
Ports
        ↓
Adapters
```

Runtime code must not bypass application services to call provider SDKs directly.

### 2.3 Provider Types Must Not Leak

Do not introduce provider-specific types into the domain or application contracts:

```text
OpenProjectWorkPackage
JiraIssue
XWikiPage
BackstageEntity
PiSession
Neo4jNode
WeaviateObject
```

### 2.4 Optional Must Mean Optional

If configured:

```yaml
enabled: false
```

or if a provider is optional and temporarily unavailable, the Brain should still start.

This applies especially to:

```text
OpenProject / Jira
XWiki / Confluence
Backstage
Docling
Pi
```

### 2.5 Important Findings Become Observations

Whenever the Brain discovers something meaningful, persist it as an `Observation`.

Examples:

```text
partial implementation found
scope changed
requirement ambiguous
documentation conflict
unexpected dependency
verification failure
human action required
verification pass
```

Selected observations must be projected into the configured human tool.

### 2.6 Long Work Must Be Asynchronous

HTTP endpoints must not wait for:

```text
repository ingestion
PDF conversion
code indexing
planning
coding
verification
```

The API should return an accepted command/workflow identifier and let workers perform the operation.

### 2.7 Verification Chain After Every Task

Run:

```bash
uv run ruff format tests brain
uv run ruff check tests brain
uv run mypy brain
uv run pytest -q
```

Do not mark a task complete until the relevant tests pass.

---

# Phase 21 — Runtime Composition Root

## Goal

Create one canonical mechanism for wiring the existing Brain library into executable applications.

This phase must happen before FastAPI, workers, CLI, or external service deployment.

---

## Task 21.1 — Audit Existing Construction Logic

Search for current constructors and factories:

```text
create_repositories
create_services
create_adapters
factory
registry
container
bootstrap
settings
provider
```

Document:

- which construction helpers already exist;
- which objects need async initialization;
- which clients need explicit shutdown;
- where settings are currently loaded;
- whether dependencies are currently created multiple times;
- any provider-specific construction leaking into application code.

### Deliverable

```text
docs/runtime/composition-audit.md
```

### Acceptance Criteria

- Existing wiring is understood.
- Duplicate construction paths are identified.
- New runtime composition will reuse existing factories where sensible.

---

## Task 21.2 — Create Typed Runtime Settings

Create a central `BrainSettings` hierarchy.

Suggested settings:

```text
BrainRuntimeSettings
PostgresSettings
Neo4jSettings
WeaviateSettings
RedisSettings
ArtifactStoreSettings
WorkManagementSettings
DocumentationSettings
DocumentConversionSettings
SoftwareCatalogSettings
SourceControlSettings
ExecutorSettings
VerificationSettings
AutomationPolicySettings
HumanApprovalSettings
```

### Requirements

Settings should support:

```text
environment variables
.env development files
explicit construction in tests
```

If YAML config is already part of the project, support it through the same typed model.

### Important Rule

Adapters should receive resolved settings. They should not independently read environment variables deep inside their implementation.

---

## Task 21.3 — Required/Optional Provider Settings

Every integration capability should support:

```text
enabled
provider
required
```

Example:

```yaml
work_management:
  enabled: true
  provider: openproject
  required: false
```

Expected behavior:

```text
enabled=false
    → do not initialize provider

required=false + provider unavailable
    → Brain starts, capability UNAVAILABLE

required=true + provider unavailable
    → readiness fails
```

---

## Task 21.4 — Implement `BrainContainer`

Create a runtime container that groups already-implemented services and ports.

The container should expose interfaces/application services rather than raw provider SDK objects wherever possible.

Expected groups:

```text
state repositories
knowledge graph repository
semantic index
event bus
artifact store
source control port
work management port
documentation ports
software catalog port
document conversion port
executor registry
project service
repository service
ingestion service
planning service
context service
execution service
verification service
observation service
```

---

## Task 21.5 — Implement `create_brain_container()`

Create one async factory:

```python
async def create_brain_container(
    settings: BrainSettings,
) -> BrainContainer:
    ...
```

Responsibilities:

```text
construct infrastructure clients
construct configured adapters
construct repositories
construct application services
construct executor registry
construct capability registry
return container
```

### Do Not

Do not perform these as construction side effects:

```text
run migrations
ingest repository
start workflow
create external project
```

---

## Task 21.6 — Runtime Shutdown

Provide one shutdown path or async context manager.

Close:

```text
PostgreSQL pool
Neo4j driver
Weaviate client
Redis
HTTP provider clients
object-storage client if needed
```

Shutdown should be idempotent.

---

## Task 21.7 — Core-Only Composition Test

Test with:

```text
Postgres enabled
Neo4j enabled
Weaviate enabled
Redis enabled
OpenProject disabled
XWiki disabled
Backstage disabled
Docling disabled
Pi disabled
```

Expected:

```text
container creation succeeds
core services available
optional adapters represented as disabled/null implementations
```

---

## Task 21.8 — Optional Provider Failure Test

Example:

```text
OpenProject enabled
required=false
URL unreachable
```

Expected:

```text
container created
Brain usable
OpenProject capability = UNAVAILABLE
```

---

## Phase 21 Completion Gate

One composition root can construct and close the complete Brain runtime without any API or CLI.

---

# Phase 22 — Capability Registry and Health Model

## Goal

Make runtime capability availability explicit and queryable.

---

## Task 22.1 — Capability Models

Implement:

```text
CapabilityName
CapabilityStatus
CapabilityDescriptor
CapabilityHealth
CapabilityRegistry
```

Statuses:

```text
AVAILABLE
DEGRADED
DISABLED
UNAVAILABLE
MISCONFIGURED
```

---

## Task 22.2 — Health-Check Contract

Where useful define:

```python
class HealthCheckPort(Protocol):
    async def health(self) -> CapabilityHealth:
        ...
```

Do not force unrelated adapters to implement it immediately if equivalent health behavior already exists.

---

## Task 22.3 — Required vs Optional Readiness

Implement a readiness evaluator.

Rules:

```text
required Postgres unavailable
    → not ready

required Neo4j unavailable
    → not ready

optional XWiki unavailable
    → ready, XWiki=UNAVAILABLE

Backstage disabled
    → ready, Backstage=DISABLED
```

---

## Task 22.4 — Runtime Capability Refresh

Provider availability may change after startup.

Support explicit refresh/recheck.

This will later be used by the scheduler and `/capabilities` endpoint.

---

## Task 22.5 — Tests

Cover:

```text
all core healthy
Postgres unavailable
Neo4j unavailable
optional OpenProject unavailable
disabled XWiki
misconfigured provider
```

---

## Phase 22 Completion Gate

The runtime can explain which capabilities are usable without trying to infer availability from exceptions during normal workflows.

---

# Phase 23 — FastAPI Control Plane

## Goal

Expose the existing Brain application services through a provider-neutral REST API.

---

## Task 23.1 — Add FastAPI Runtime Dependencies

Add FastAPI and Uvicorn versions compatible with the project.

Avoid mixing API schemas directly with persistence models.

---

## Task 23.2 — FastAPI Application Factory

Implement:

```python
def create_app(settings: BrainSettings | None = None) -> FastAPI:
    ...
```

Avoid constructing global DB clients during import.

---

## Task 23.3 — Lifespan

Startup:

```text
resolve settings
create BrainContainer
perform required readiness initialization
store container on app state
```

Shutdown:

```text
close container
```

---

## Task 23.4 — Correlation Middleware

For each request:

```text
accept valid incoming correlation ID or generate one
store in request context
propagate into commands/events/logs
return in response header
```

---

## Task 23.5 — API Error Envelope

Standardize:

```json
{
  "code": "...",
  "message": "...",
  "correlation_id": "...",
  "details": {}
}
```

Do not expose raw tracebacks by default.

---

## Task 23.6 — Health Routes

Implement:

```text
GET /health/live
GET /health/ready
```

---

## Task 23.7 — Capability Route

Implement:

```text
GET /api/v1/capabilities
```

---

## Task 23.8 — System Routes

Implement:

```text
GET /api/v1/system/status
GET /api/v1/system/version
POST /api/v1/system/reconcile
```

`reconcile` will later enqueue a command.

---

## Task 23.9 — Project Routes

Implement:

```text
POST /api/v1/projects
GET /api/v1/projects
GET /api/v1/projects/{id}
PATCH /api/v1/projects/{id}
POST /api/v1/projects/{id}/analyze
GET /api/v1/projects/{id}/topology
GET /api/v1/projects/{id}/knowledge-status
```

---

## Task 23.10 — Repository Routes

Implement:

```text
POST /api/v1/projects/{id}/repositories
GET /api/v1/repositories/{id}
POST /api/v1/repositories/{id}/sync
POST /api/v1/repositories/{id}/ingest
GET /api/v1/repositories/{id}/status
GET /api/v1/repositories/{id}/changes
GET /api/v1/repositories/{id}/symbols
POST /api/v1/repositories/{id}/impact-analysis
```

---

## Task 23.11 — Document Routes

Implement:

```text
POST /api/v1/projects/{id}/documents
GET /api/v1/documents/{id}
GET /api/v1/documents/{id}/versions
POST /api/v1/documents/{id}/ingest
POST /api/v1/documents/{id}/reprocess
GET /api/v1/documents/{id}/structure
GET /api/v1/documents/{id}/knowledge
```

---

## Task 23.12 — Requirement Routes

Implement:

```text
POST /api/v1/requirements
GET /api/v1/requirements/{id}
PATCH /api/v1/requirements/{id}
POST /api/v1/requirements/extract
POST /api/v1/requirements/{id}/analyze
GET /api/v1/requirements/{id}/coverage
GET /api/v1/requirements/{id}/related-code
```

---

## Task 23.13 — Work Item Routes

Implement:

```text
POST /api/v1/work-items
GET /api/v1/work-items/{id}
PATCH /api/v1/work-items/{id}
POST /api/v1/work-items/{id}/analyze
POST /api/v1/work-items/{id}/plan
POST /api/v1/work-items/{id}/context
POST /api/v1/work-items/{id}/run
POST /api/v1/work-items/{id}/pause
POST /api/v1/work-items/{id}/resume
POST /api/v1/work-items/{id}/cancel
POST /api/v1/work-items/{id}/retry
GET /api/v1/work-items/{id}/executions
GET /api/v1/work-items/{id}/observations
```

---

## Task 23.14 — Context Routes

Implement:

```text
POST /api/v1/contexts/build
GET /api/v1/contexts/{id}
GET /api/v1/contexts/{id}/explanation
POST /api/v1/contexts/{id}/expand
POST /api/v1/contexts/search
POST /api/v1/contexts/symbol
POST /api/v1/contexts/related-files
POST /api/v1/contexts/related-tests
```

---

## Task 23.15 — Code Intelligence Routes

Implement:

```text
GET /api/v1/code/symbols/{id}
GET /api/v1/code/symbols/{id}/callers
GET /api/v1/code/symbols/{id}/callees
GET /api/v1/code/symbols/{id}/tests
POST /api/v1/code/search
POST /api/v1/code/impact
GET /api/v1/code/files/{id}/dependencies
```

---

## Task 23.16 — Knowledge Routes

Implement:

```text
POST /api/v1/knowledge/search
GET /api/v1/knowledge/entities/{id}
GET /api/v1/knowledge/entities/{id}/relations
POST /api/v1/knowledge/traverse
GET /api/v1/knowledge/conflicts
POST /api/v1/knowledge/conflicts/{id}/resolve
```

---

## Task 23.17 — Execution Routes

Implement:

```text
POST /api/v1/executions
GET /api/v1/executions/{id}
POST /api/v1/executions/{id}/cancel
POST /api/v1/executions/{id}/retry
GET /api/v1/executions/{id}/artifacts
GET /api/v1/executions/{id}/evidence
GET /api/v1/executions/{id}/diff
```

---

## Task 23.18 — Verification Routes

Implement:

```text
POST /api/v1/executions/{id}/verify
GET /api/v1/verifications/{id}
POST /api/v1/verifications/{id}/rerun
GET /api/v1/verifications/{id}/evidence
GET /api/v1/verifications/{id}/failures
```

---

## Task 23.19 — Pull Request Routes

Implement canonical routes:

```text
POST /api/v1/executions/{id}/pull-request
GET /api/v1/pull-requests/{id}
POST /api/v1/pull-requests/{id}/refresh
```

Do not make these routes provider-specific.

---

## Task 23.20 — Observation Routes

Implement:

```text
GET /api/v1/observations
GET /api/v1/work-items/{id}/observations
POST /api/v1/observations/{id}/acknowledge
POST /api/v1/observations/{id}/resolve
POST /api/v1/work-items/{id}/feedback
```

---

## Task 23.21 — OpenAPI and Route Tests

Test:

```text
schema generation
validation
404 behavior
error envelope
correlation IDs
core CRUD/query paths
```

---

## Phase 23 Completion Gate

The Brain starts as a FastAPI service, exposes canonical APIs, and does not depend on optional human integrations for startup.

---

# Phase 24 — Command and Job Dispatch

## Goal

Make long-running work asynchronous and trigger-neutral.

---

## Task 24.1 — Command Envelope

Implement:

```text
command_id
command_type
project_id
requested_at
requested_by
trigger_type
correlation_id
payload
```

Trigger types:

```text
USER
EVENT
SCHEDULED
INTERNAL
```

---

## Task 24.2 — Canonical Commands

Create:

```text
AnalyzeProjectCommand
SyncRepositoryCommand
IngestRepositoryCommand
IngestDocumentCommand
ExtractRequirementsCommand
AnalyzeWorkItemCommand
PlanWorkItemCommand
BuildContextCommand
RunWorkItemCommand
ExecuteWorkItemCommand
VerifyExecutionCommand
CreatePullRequestCommand
ReconcileProjectCommand
```

---

## Task 24.3 — Local Dispatcher

Implement in-process dispatcher for unit tests.

This makes command handlers testable without Redis.

---

## Task 24.4 — Redis Queue Adapter

Implement or reuse existing queue abstraction.

Required behavior:

```text
enqueue
consume
acknowledge
retry
idempotency
failure persistence
```

If dead-letter queues are used, keep them behind the queue port.

---

## Task 24.5 — HTTP 202 Pattern

Long-running endpoints should return a standard result:

```json
{
  "command_id": "...",
  "workflow_id": "...",
  "status": "ACCEPTED"
}
```

---

## Task 24.6 — User and Event Convergence Tests

Verify:

```text
POST /work-items/{id}/run
```

and:

```text
WorkItemAssigned event
```

both produce the same `RunWorkItemCommand` semantics.

---

## Phase 24 Completion Gate

Long-running API operations are queued and the orchestration path no longer depends on whether the trigger came from a human or event.

---

# Phase 25 — Brain Worker Runtime

## Goal

Create a process that consumes commands and invokes the existing application services/workflows.

---

## Task 25.1 — Worker Entry Point

Add:

```text
brain/workers/main.py
```

Features:

```text
settings loading
BrainContainer creation
queue connection
graceful shutdown
structured logging
```

---

## Task 25.2 — Command Dispatcher

Map canonical command types to application handlers.

Do not place business logic in the dispatcher.

---

## Task 25.3 — Ingestion Handlers

Handle:

```text
SyncRepositoryCommand
IngestRepositoryCommand
IngestDocumentCommand
```

---

## Task 25.4 — Planning Handlers

Handle:

```text
ExtractRequirementsCommand
AnalyzeWorkItemCommand
PlanWorkItemCommand
```

---

## Task 25.5 — Context Handler

Handle:

```text
BuildContextCommand
```

Persist the generated ContextCapsule if existing services do not already do so.

---

## Task 25.6 — Execution Handler

Handle:

```text
ExecuteWorkItemCommand
```

Execution failure must be persisted and must not crash the worker process.

---

## Task 25.7 — Verification Handler

Handle:

```text
VerifyExecutionCommand
```

---

## Task 25.8 — PR Handler

Handle:

```text
CreatePullRequestCommand
```

Subject to PR-readiness policy.

---

## Task 25.9 — Command Failure Model

Persist:

```text
command ID
attempt
failure category
message
correlation ID
retry eligibility
```

---

## Task 25.10 — End-to-End Queue Test

Test:

```text
API request
  ↓
command queued
  ↓
worker consumes
  ↓
application service invoked
  ↓
state updated
```

---

## Phase 25 Completion Gate

FastAPI + Worker form an asynchronous Brain application.

---

# Phase 26 — Observation and Engineering Journal

## Goal

Create a canonical, evidence-backed representation of meaningful Brain findings.

---

## Task 26.1 — Audit Existing Finding Models

Search for existing concepts:

```text
feedback
finding
warning
observation
diagnostic
issue
blocker
```

Reuse or migrate rather than duplicate.

---

## Task 26.2 — Observation Model

Implement/finalize:

```text
Observation
ObservationType
ObservationSeverity
ObservationVisibility
ObservationStatus
```

Suggested types:

```text
DISCOVERY
WARNING
CONFLICT
IMPLEMENTATION_STATUS
SCOPE_CHANGE
ASSUMPTION
VERIFICATION_FAILURE
VERIFICATION_PASS
BLOCKER
DEPENDENCY_DISCOVERED
ARCHITECTURE_VIOLATION
HUMAN_ACTION_REQUIRED
```

---

## Task 26.3 — Observation Relationships

Allow association with:

```text
Project
Requirement
WorkItem
Repository revision
ContextCapsule
Execution
Verification
Artifact
Evidence
Decision
```

---

## Task 26.4 — Observation Persistence

Add repository/table/migration if not already supported.

Store observation independently of external comment projection.

---

## Task 26.5 — Observation Service

Provide:

```text
create
deduplicate
query
acknowledge
resolve
```

---

## Task 26.6 — Observation Policy

Determine whether an observation should be:

```text
INTERNAL only
TEAM visible
IMPORTANT / human action
```

Start with deterministic policy rules.

---

## Task 26.7 — `ObservationCreated` Event

Every newly persisted meaningful observation emits a canonical event.

---

## Task 26.8 — Noise-Control Tests

Must **not** create human-relevant observation for:

```text
file parsing completed
embedding stored
Neo4j write completed
worker heartbeat
```

Must create meaningful observation for:

```text
partial implementation
verification failure
requirement ambiguity
documentation conflict
architecture violation
```

---

## Phase 26 Completion Gate

The Brain has a canonical engineering journal independent of any human tool.

---

# Phase 27 — Human Activity Projection

## Goal

Project selected observations into whichever human tools are configured.

---

## Task 27.1 — Define `HumanActivityPort`

```python
class HumanActivityPort(Protocol):
    async def publish_observation(
        self,
        target: ExternalReference,
        observation: Observation,
    ) -> HumanActivityReference:
        ...
```

---

## Task 27.2 — Null Adapter

When no human tool exists:

```text
Observation remains stored
projection safely no-ops or records DISABLED
```

No workflow should fail merely because no human-comment system is configured.

---

## Task 27.3 — Projection Tracking

Persist:

```text
observation_id
provider
external target
external comment/activity ID
published_at
publication status
```

This is required for idempotency.

---

## Task 27.4 — Provider-Neutral Formatter

Create concise human-readable output.

Example:

```text
Brain observation — existing implementation found

Login-attempt tracking already exists in AuthenticationService.
Remaining work appears limited to account-lock enforcement and tests.
```

---

## Task 27.5 — OpenProject Activity/Comment Adapter

Implement the first reference HumanActivityPort adapter.

Requirements:

```text
publish comment/activity
link to task
avoid duplicate comment
store external comment ID
```

---

## Task 27.6 — Jira Adapter Skeleton

Implement enough to prove the port is interchangeable.

Run shared contract tests against OpenProject and Jira adapters.

---

## Task 27.7 — Human Feedback Normalization

Comments/replies that are intended as Brain feedback should normalize to:

```text
HumanFeedbackReceived
```

Record:

```text
author
provider
external comment ID
work item
message
timestamp
```

---

## Task 27.8 — Feedback Resume Service

When workflow waits for human input:

```text
HumanFeedbackReceived
      ↓
store feedback
      ↓
update requirement/decision where appropriate
      ↓
invalidate stale context
      ↓
resume workflow
```

---

## Phase 27 Completion Gate

Important Brain findings can appear as comments in OpenProject, while the same application logic remains compatible with Jira or no human tool.

---

# Phase 28 — Workflow Orchestrator Runtime

## Goal

Connect existing internal services into resilient executable workflows.

If LangGraph graphs were already built in earlier phases, adapt and complete them rather than duplicating them.

---

## Task 28.1 — Audit Existing Orchestration

Identify:

```text
LangGraph graphs
workflow state
checkpoint integration
retry policies
planning workflow
execution workflow
verification workflow
```

Document what is reusable.

---

## Task 28.2 — Canonical Workflow State

Keep state small:

```text
workflow_id
project_id
work_item_id
repository_id
base_revision
context_capsule_id
execution_id
verification_id
stage
retry_count
waiting_for_human
correlation_id
```

Do not store large documents/source code in graph state.

---

## Task 28.3 — Main Engineering Workflow

Implement/complete stages:

```text
LOAD WORK ITEM
SYNC CURRENT STATE
UNDERSTAND REQUIREMENT
ANALYZE IMPLEMENTATION STATUS
CREATE OBSERVATION IF IMPORTANT
BUILD CONTEXT
ASSESS RISK / COMPLEXITY
SELECT EXECUTOR
APPROVAL GATE
EXECUTE
COLLECT EVIDENCE
VERIFY
RETRY / ESCALATE
PR READINESS
CREATE PR IF ALLOWED
PUBLISH OBSERVATION
UPDATE BRAIN
COMPLETE
```

---

## Task 28.4 — Ingestion Workflow

Stages:

```text
fetch source
identify revision/version
parse
normalize
extract knowledge
update graph
update semantic index
mark current
```

---

## Task 28.5 — Planning Workflow

Stages:

```text
collect requirements
assess ambiguity
inspect current implementation
decompose work
validate plan
sync/publish WorkItems
```

---

## Task 28.6 — Verification Workflow

Stages:

```text
build verification plan
run deterministic checks
structural analysis
semantic verification
aggregate evidence
produce verdict
create observation if necessary
```

---

## Task 28.7 — Application-Service Boundary Test

Add architecture test preventing orchestrator modules from importing provider adapters directly.

---

## Task 28.8 — Checkpointing

Use existing Postgres/LangGraph checkpoint implementation.

Remember:

```text
checkpoint = orchestration resume position
execution record = engineering history
```

Do not merge them.

---

## Task 28.9 — Retry Classification

Distinguish:

```text
transient provider failure
model failure
execution failure
verification failure
human decision required
invalid input
```

Each type should have different retry behavior.

---

## Task 28.10 — Crash Recovery Tests

Simulate crash after:

```text
context creation
execution start
verification start
observation creation
external comment publication
```

Verify idempotent resume.

---

## Phase 28 Completion Gate

A WorkItem workflow can execute, pause, retry, wait for a human, recover after process failure, verify, and complete.

---

# Phase 29 — Scheduler and Reconciliation Runtime

## Goal

Guarantee eventual consistency when webhooks are missed or providers temporarily fail.

---

## Task 29.1 — Scheduler Entry Point

Create:

```text
brain/scheduler/main.py
```

Use the same `BrainContainer`.

---

## Task 29.2 — Repository Reconciliation

For configured repositories:

```text
compare tracked revision with remote revision
schedule sync/ingestion if stale
```

---

## Task 29.3 — Work-Management Reconciliation

Use provider watermarks/timestamps when available.

Detect missed changes.

---

## Task 29.4 — Documentation Reconciliation

Check configured external documentation systems for new versions/changes.

---

## Task 29.5 — Projection Freshness

Check whether:

```text
Neo4j projection is behind canonical Postgres state
Weaviate index is behind current document/code revision
```

Schedule repair rather than silently serving stale data.

---

## Task 29.6 — Stuck Execution Detection

Detect executions stuck beyond configured threshold.

Possible outcomes:

```text
automatic recovery
retry
Observation(HUMAN_ACTION_REQUIRED)
```

---

## Task 29.7 — Observation Projection Retry

Retry failed comments idempotently.

Do not create duplicate human comments.

---

## Phase 29 Completion Gate

The system converges back to correct state after missed events or temporary integration failures.

---

# Phase 30 — CLI

## Goal

Provide a developer/admin interface without requiring ad-hoc Python scripts.

---

## Task 30.1 — CLI Framework

Use project-appropriate library such as Typer/Click/argparse.

CLI must use the same composition root and application services.

---

## Task 30.2 — Runtime Commands

Implement:

```bash
brainctl status
brainctl health
brainctl capabilities
```

---

## Task 30.3 — Project Commands

```bash
brainctl project list
brainctl project create
brainctl project show
```

---

## Task 30.4 — Repository Commands

```bash
brainctl repository add
brainctl repository sync
brainctl repository ingest
brainctl repository status
```

---

## Task 30.5 — Context Commands

```bash
brainctl context build
brainctl context show
brainctl context explain
```

---

## Task 30.6 — Work Item Commands

```bash
brainctl work-item create
brainctl work-item show
brainctl work-item run
brainctl work-item retry
```

---

## Task 30.7 — Execution and Verification Commands

```bash
brainctl execution show
brainctl execution diff
brainctl execution verify
```

---

## Task 30.8 — Observation Commands

```bash
brainctl observation list
brainctl observation show
brainctl observation acknowledge
brainctl observation resolve
```

---

## Phase 30 Completion Gate

A developer can operate and inspect the Brain without writing custom Python.

---

# Phase 31 — Packaging and Executable Entry Points

## Goal

Turn the package into an installable application surface.

---

## Task 31.1 — `project.scripts`

Add:

```toml
[project.scripts]
brain-api = "brain.api.runner:main"
brain-worker = "brain.workers.main:main"
brain-scheduler = "brain.scheduler.main:main"
brainctl = "brain.cli.main:main"
```

---

## Task 31.2 — API Runner

Wrap Uvicorn configuration:

```text
host
port
log level
workers
```

---

## Task 31.3 — Version Metadata

Expose package/application version and optional Git build SHA.

---

## Task 31.4 — Clean Installation Test

Build wheel, install into clean environment, verify all commands are available.

---

## Phase 31 Completion Gate

The project is no longer only a library; it has supported runtime entry points.

---

# Phase 32 — Core Brain Docker Runtime

## Goal

Run the Brain itself under Docker Compose.

---

## Task 32.1 — Brain Dockerfile

Create one image capable of running:

```text
brain-api
brain-worker
brain-scheduler
brainctl
```

---

## Task 32.2 — Core Compose Services

Core `compose.yaml` should contain:

```text
brain-api
brain-worker
brain-scheduler
postgres
neo4j
weaviate
redis
minio
```

Do not include all optional human tools as mandatory dependencies.

---

## Task 32.3 — Health Checks

Add health checks for required services.

Brain startup ordering should depend only on required capabilities.

---

## Task 32.4 — Migration Strategy

Choose one explicit model:

```text
one-shot migration service
or
operator/admin runs migration before runtime
```

Do not allow every worker/API replica to race migrations.

---

## Task 32.5 — Persistent Volumes

Configure persistent storage for:

```text
PostgreSQL
Neo4j
Weaviate
MinIO
```

---

## Task 32.6 — Core Smoke Test

From clean state:

```text
docker compose up
migration completes
API becomes ready
worker consumes command
scheduler runs
```

---

## Phase 32 Completion Gate

`docker compose up` starts the operational Brain core.

---

# Phase 33 — Docling Serve Reference Integration

## Goal

Provide PDF/DOCX/etc. conversion as an optional replaceable capability.

---

## Task 33.1 — Audit Document Conversion Contract

If an equivalent port already exists, reuse it.

Otherwise define:

```text
DocumentConversionPort
```

Operations:

```text
convert
supported formats
health
```

---

## Task 33.2 — Docling Serve Adapter

Implement HTTP adapter.

Normalize output into the existing canonical ingestion model.

The rest of the Brain must not depend on Docling's schema.

---

## Task 33.3 — Native Structured Fallback

Do not route these through Docling unnecessarily:

```text
Markdown
OpenAPI
YAML
JSON
source code
```

Use native parsers.

---

## Task 33.4 — Optional Compose Overlay/Profile

Add Docling separately from core compose.

---

## Task 33.5 — Disabled/Unavailable Behavior

Expected:

```text
Brain ready
Docling capability disabled/unavailable
Markdown ingestion works
PDF/DOCX conversion returns clear capability error
```

---

## Phase 33 Completion Gate

Document conversion works when Docling is available without making Docling a core dependency.

---

# Phase 34 — OpenProject Reference Integration

## Goal

Provide OpenProject as the reference work-management environment and prove provider interchangeability.

---

## Task 34.1 — Optional OpenProject Compose

Create separate overlay/profile.

Document ports, volumes and initial credentials through environment templates.

---

## Task 34.2 — Configure Existing OpenProject Adapter

Wire through `WorkManagementPort` using runtime settings.

No application service should import OpenProject-specific code.

---

## Task 34.3 — Webhook Endpoint

Provider-specific input route may be:

```text
POST /api/v1/webhooks/openproject
```

Immediately validate and normalize to canonical events.

---

## Task 34.4 — External Mapping

Persist:

```text
Brain WorkItem ID
OpenProject work package ID
project mapping
sync metadata
```

---

## Task 34.5 — Brain Actor Mapping

Map configured OpenProject user/account to canonical `Actor`.

---

## Task 34.6 — Assignment Automation

When task is assigned to Brain actor:

```text
OpenProject webhook
      ↓
WorkItemAssigned
      ↓
policy check
      ↓
RunWorkItemCommand
```

---

## Task 34.7 — Observation Comments

Implement/validate HumanActivityPort comment projection.

Examples:

```text
existing implementation found
verification failed
human input required
verification passed
PR created
```

---

## Task 34.8 — Human Reply

A relevant OpenProject comment should become:

```text
HumanFeedbackReceived
```

---

## Phase 34 Completion Gate

An OpenProject task can trigger the Brain, receive Brain comments, and send human feedback back into the workflow.

---

# Phase 35 — XWiki Reference Integration

## Goal

Provide a human-friendly documentation system as an optional knowledge source.

---

## Task 35.1 — Optional XWiki Compose

Host XWiki separately from Brain core.

---

## Task 35.2 — Documentation Adapter

Implement/reuse `DocumentationPort` support for:

```text
page fetch
hierarchy
version
attachments
links
changed pages
```

---

## Task 35.3 — Canonical Mapping

Normalize XWiki pages into:

```text
Document
DocumentVersion
DocumentNode
```

---

## Task 35.4 — Change Events

Normalize changes to:

```text
DocumentChanged
```

---

## Task 35.5 — Project/Space Mapping

Use `ExternalReference` rather than XWiki IDs as internal identities.

---

## Task 35.6 — Knowledge Publication Policy

Do not publish every Observation to XWiki.

Allow future controlled publication of:

```text
architecture decisions
stable generated documentation
important knowledge corrections
```

---

## Phase 35 Completion Gate

XWiki enriches the Brain but can be removed/disabled without impacting the core system.

---

# Phase 36 — Backstage Reference Integration

## Goal

Support human-declared software topology where available while keeping derived topology as the default fallback.

---

## Task 36.1 — Reference Backstage Environment

Treat Backstage as optional and potentially less common than issue trackers/wikis.

Document that the Brain must not expect every organization to maintain it.

---

## Task 36.2 — Catalog Adapter

Map:

```text
Domain
System
Component
API
Resource
owner
dependency
```

into canonical software-model entities.

---

## Task 36.3 — Reconciliation

Compare:

```text
human-declared topology
brain-discovered topology
```

Do not overwrite conflicts.

---

## Task 36.4 — Conflict Observation

Example:

```text
Backstage does not declare Redis dependency.
Code/runtime evidence shows Redis is used.
```

Create a `CONFLICT` or `DEPENDENCY_DISCOVERED` Observation based on policy.

---

## Task 36.5 — Disabled Mode

Verify:

```text
Backstage disabled
DerivedSoftwareCatalog available
Brain ready
```

---

## Phase 36 Completion Gate

Backstage provides higher-confidence declared topology when available, but the Brain remains fully capable of deriving topology itself.

---

# Phase 37 — Pi Executor Runtime Integration

## Goal

Run the already-designed Pi coding executor inside the operational Brain runtime.

---

## Task 37.1 — Audit Existing Pi Adapter

Verify boundaries:

```text
ExecutionRequest
ContextCapsule
workspace
permissions
ExecutionResult
```

Ensure no Pi-specific session type leaked into canonical execution models.

---

## Task 37.2 — Runtime Configuration

Support:

```yaml
executors:
  coding:
    provider: pi
```

---

## Task 37.3 — Capability Health

Expose Pi availability through CapabilityRegistry.

---

## Task 37.4 — Brain Retrieval Tools

Validate executor access to:

```text
get_symbol_context
find_related_files
find_related_tests
get_requirement
get_architecture_constraints
search_project_knowledge
request_more_context
```

These should call Brain application services, not databases directly.

---

## Task 37.5 — Workspace Isolation

Every execution must record:

```text
repository
base branch
base commit
worktree
working branch
```

---

## Task 37.6 — Pi Failure Isolation

Pi/model/tool failure must:

```text
mark execution failed
persist evidence/log references
possibly retry
not terminate worker process
```

---

## Phase 37 Completion Gate

A queued WorkItem can execute through Pi using a bounded ContextCapsule in an isolated worktree.

---

# Phase 38 — Pull Request Runtime Integration

## Goal

Connect verified execution to source-control pull/merge-request creation.

---

## Task 38.1 — Runtime `PullRequestPort`

Wire existing contract through the composition root.

---

## Task 38.2 — Reference Provider Adapter

Implement chosen provider first:

```text
GitLab merge request
or
GitHub pull request
```

---

## Task 38.3 — PR Readiness Enforcement

Application service must check:

```text
verification verdict == PASS
policy permits PR creation
```

before provider call.

---

## Task 38.4 — PR Observation

Create observation after PR/MR creation:

```text
Verification passed. Merge Request !123 was created.
```

Project it to work-management task.

---

## Task 38.5 — Merge Event

Normalize provider merge event:

```text
PullRequestMerged
      ↓
RepositoryRevisionChanged
      ↓
re-ingestion
```

---

## Phase 38 Completion Gate

Verified code creates a PR/MR, the work item is updated visibly, and merged code returns into Brain knowledge.

---

# Phase 39 — Full Reference End-to-End Environment

## Goal

Prove the complete architecture with a reproducible sample scenario.

---

## Task 39.1 — Reference Environment Compose

Document how to start:

```text
Brain core
OpenProject
XWiki
Docling
optional Backstage
source-control provider/model dependencies as required
```

---

## Task 39.2 — Seed Sample Repository

Create deterministic project containing:

```text
README
architecture documentation
requirements
authentication code
tests
configuration
partial implementation
```

---

## Task 39.3 — Seed Requirement and Work Item

Example:

```text
Implement account locking after five failed login attempts.
```

The repository should already contain login-attempt tracking so the Brain can discover partial implementation.

---

## Task 39.4 — Verify Implementation-Status Observation

Expected:

```text
Brain detects partial implementation
Observation created
OpenProject comment posted
```

---

## Task 39.5 — Verify Context Quality

Context must include:

```text
requirement
auth service
user model/repository as relevant
security configuration
related tests
architecture decision if present
```

Context should exclude known unrelated modules.

Assert token budget.

---

## Task 39.6 — Execute Through Pi or Controlled Fake Executor

For deterministic CI, a fake executor may be used first.

A Pi run should also be supported for manual/e2e validation.

---

## Task 39.7 — Force First Verification Failure

Use a controlled fixture or fake executor sequence where one acceptance criterion is missing.

Expected:

```text
verification FAIL
failure Observation
human-tool comment
retry context includes feedback
```

---

## Task 39.8 — Successful Retry

Expected:

```text
verification PASS
PR readiness PASS
PR created if policy allows
Observation projected
```

---

## Task 39.9 — Merge and Re-Ingest

Expected:

```text
merged revision detected
code graph updated
knowledge graph updated
semantic index updated
technical work status updated
```

---

## Task 39.10 — Human Feedback Scenario

Create an ambiguous task requiring clarification.

Expected:

```text
HUMAN_ACTION_REQUIRED Observation
workflow pauses
OpenProject comment published
human replies
HumanFeedbackReceived
context rebuilt
workflow resumes
```

---

## Phase 39 Completion Gate

The entire architecture functions as an observable, recoverable system and visibly collaborates with humans.

---

# Phase 40 — Production Hardening

## Goal

Prepare for controlled real-team use.

---

## Task 40.1 — API Authentication

Protect Brain API.

Separate identities:

```text
human user
service account
webhook provider
executor
```

---

## Task 40.2 — Authorization

Policies should cover:

```text
project access
execution triggering
observation resolution
PR creation
admin operations
```

---

## Task 40.3 — Webhook Authentication

Validate provider signatures/tokens before normalization.

---

## Task 40.4 — Secret Management

Do not persist integration credentials as plaintext project configuration.

---

## Task 40.5 — Rate Limiting

Protect expensive operations:

```text
project analysis
context build
execution
verification
```

---

## Task 40.6 — Concurrency Controls

Prevent conflicting automated changes to the same repository/worktree/branch.

---

## Task 40.7 — Audit Trail

Record:

```text
who/what triggered command
which model/executor ran
what base revision was used
what changed
what evidence was collected
what verification decided
what observations were published
what external tool was updated
```

---

## Task 40.8 — Metrics

Expose metrics for:

```text
API latency
queue depth
workflow duration
command failures
execution outcomes
verification pass/fail
context token count
JIT retrieval requests
provider availability
observation projection success/failure
```

---

## Task 40.9 — Backup and Rebuild Strategy

Document:

```text
Postgres backup
Neo4j backup/rebuild
Weaviate rebuild strategy
MinIO backup
```

Clarify which data is canonical and which is a rebuildable projection/index.

---

## Phase 40 Completion Gate

The system is ready for controlled production-like pilot use.

---

# API Trigger Matrix

Legend:

```text
U = user
E = event
S = scheduled
A = agent/internal tool
```

| Operation | U | E | S | A |
|---|---:|---:|---:|---:|
| Create project | ✓ | | | |
| Register repository | ✓ | | | |
| Sync repository | ✓ | ✓ | ✓ | |
| Ingest repository | ✓ | ✓ | ✓ | |
| Ingest document | ✓ | ✓ | ✓ | |
| Extract requirements | ✓ | ✓ | | |
| Analyze work item | ✓ | ✓ | | ✓ |
| Plan work item | ✓ | ✓ | | |
| Build context | ✓ | ✓ | | ✓ |
| Expand context | ✓ | | | ✓ |
| Run work item | ✓ | ✓ | | |
| Execute coding task | ✓ | ✓ | | |
| Verify execution | ✓ | ✓ | | |
| Retry execution | ✓ | ✓ | | |
| Create PR | ✓ | ✓ | | |
| Reconcile project | ✓ | | ✓ | |
| Publish observation | | ✓ | | |
| Receive human feedback | | ✓ | | |
| Resolve knowledge conflict | ✓ | | | |
| Refresh capabilities | ✓ | | ✓ | |

---

# Event Matrix

## Repository Events

```text
RepositoryRegistered
RepositoryRevisionChanged
RepositoryIngested
CodeGraphUpdated
```

## Document Events

```text
DocumentChanged
DocumentIngested
KnowledgeUpdated
```

## Work Events

```text
WorkItemCreated
WorkItemChanged
WorkItemAssigned
HumanFeedbackReceived
```

## Execution Events

```text
ExecutionRequested
ExecutionStarted
ExecutionCompleted
ExecutionFailed
```

## Verification Events

```text
VerificationRequested
VerificationFailed
VerificationPassed
```

## Observation Events

```text
ObservationCreated
ObservationProjected
ObservationProjectionFailed
ObservationAcknowledged
ObservationResolved
```

## Pull Request Events

```text
PRReadinessPassed
PullRequestCreated
PullRequestMerged
```

---

# Cross-Phase Testing Requirements

## Architecture Tests

Prevent dependencies such as:

```text
API → OpenProject SDK
orchestrator → Jira adapter
orchestrator → Neo4j driver
domain → provider package
```

Allowed:

```text
API → application service
orchestrator → application service
application service → port
adapter → provider SDK
```

## Adapter Contract Tests

Shared contract suites should eventually run against:

```text
OpenProject / Jira
XWiki / Confluence
DerivedSoftwareCatalog / Backstage
```

## Runtime Integration Tests

Test:

```text
API + Postgres
API + worker + queue
workflow + checkpoint
capability health
```

## Observation Tests

Verify:

```text
meaningful finding → Observation
important Observation → external comment
internal telemetry → no comment
retry → no duplicate comment
```

## Optional Provider Tests

For every optional provider:

```text
disabled → Brain starts
unavailable + required=false → Brain starts
unavailable + required=true → readiness false
```

---

# Recommended Immediate Implementation Order

Do not start by hosting all external applications.

Implement runtime boundaries first:

```text
21 Composition root
22 Capability registry
23 FastAPI
24 Command/job dispatch
25 Worker
26 Observation journal
27 HumanActivityPort
28 Orchestrator runtime
29 Scheduler
30 CLI
31 Executable packaging
32 Core Docker runtime
```

Then reference integrations:

```text
33 Docling
34 OpenProject
35 XWiki
36 Backstage
37 Pi runtime
38 PR integration
39 Full E2E
40 Production hardening
```

This order prevents human tools from becoming accidental dependencies of the Brain.

---

# Milestone 1 — Brain Becomes an Application

Required phases:

```text
21–32
```

Success:

```text
brain-api starts
brain-worker starts
brain-scheduler starts
brainctl works
project can be created
repository can be registered
ingestion can run
internal WorkItem can be created
context can be built
fake execution can run
verification can run
Observation can be stored
```

No external human tool is required.

---

# Milestone 2 — Reference Software-Engineering Automation

Add:

```text
Docling
OpenProject
Pi
PR provider
```

Success flow:

```text
OpenProject task
      ↓
Brain context
      ↓
Pi execution
      ↓
verification
      ↓
OpenProject observation
      ↓
PR
```

---

# Milestone 3 — Interchangeable Human Ecosystem

Add:

```text
XWiki
Backstage optional
Jira adapter proof
human feedback loop
reconciliation
production hardening
```

Success:

```text
OpenProject can be replaced by Jira
XWiki can be replaced by Confluence contractually
Backstage can be disabled
Brain continues functioning
```

---

# Final Definition of Done

## Runtime

- `brain-api`, `brain-worker`, `brain-scheduler`, and `brainctl` exist.
- All use one composition root.

## API

- Canonical project/repository/document/requirement/work/context/code/knowledge/execution/verification/observation APIs exist.
- Long work is asynchronous.
- Provider-specific types do not leak into API/application contracts.

## Orchestration

- User and event triggers converge on canonical commands.
- Workflow state remains reference-oriented and small.
- Workflows recover from crashes.
- Human-input waits can resume.

## Human Tools

- OpenProject is an adapter, not a core model.
- Jira can implement the same work-management and activity contracts.
- XWiki is optional and interchangeable with another documentation provider.
- Backstage is optional.

## Observations

- Important findings are canonical entities.
- Only useful observations are projected to humans.
- Projection is idempotent.
- Human replies become feedback events.

## Context

- Context budgets are respected.
- Context can use requirements, code graph, knowledge graph, semantic retrieval, history, tests and verification feedback.
- Agents can request just-in-time context.

## Execution

- A replaceable executor receives a bounded ContextCapsule.
- Work happens in an isolated workspace.
- Execution output is structured and persisted.

## Verification

- Deterministic, structural and semantic verification can run.
- Verification failure blocks automatic PR.
- Failure feedback can drive retry.

## Deployment

- Brain core starts without OpenProject, XWiki, Backstage or Docling.
- Optional reference environment can enable them.
- Capability registry reports their status accurately.

## Traceability

The system can reconstruct:

```text
Requirement
      ↓
WorkItem
      ↓
ContextCapsule
      ↓
Execution
      ↓
Artifact / Evidence
      ↓
Verification
      ↓
Observation
      ↓
Pull Request
```

---

# Coding Agent Completion Report Format

After each task, report:

```text
Task:
<phase.task and title>

Implemented:
- ...

Files changed:
- ...

Contracts changed:
- none / details

Database migrations:
- none / details

Tests added:
- ...

Verification executed:
- uv run ruff format tests brain
- uv run ruff check tests brain
- uv run mypy brain
- uv run pytest -q

Result:
PASS / PARTIAL / BLOCKED

Known limitations:
- ...

Follow-up:
- ...
```

A task is complete only when its acceptance criteria and verification pass.
