# Software Development Brain

> A persistent, version-aware, tool-agnostic brain for software development that understands projects, builds precise task-specific context, assigns work to humans or AI agents, verifies code before pull requests, and communicates meaningful engineering observations back into the tools humans already use.

---

## 1. Current State of the Repository

The repository currently contains the internal engine of the Software Development Brain. The already implemented phases established the following layers:

```text
domain
  ↓
ports / contracts
  ↓
application services
  ↓
adapters
```

The project is therefore currently a **library**, not yet an operable application.

There is no application runtime yet:

```text
no FastAPI service
no CLI entry point
no worker process
no scheduler / reconciliation process
no [project.scripts] runtime commands
no application Docker image
```

The current `compose.yaml` only starts infrastructure used by adapters and tests:

```text
PostgreSQL
Neo4j
Weaviate
```

It does **not** run the Brain itself.

Current development workflow:

```bash
docker compose up -d
uv run pytest -q

uv run ruff format tests brain
uv run ruff check tests brain
uv run mypy brain
uv run pytest -q
```

Database migrations:

```powershell
$env:BRAIN_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
uv run alembic upgrade head
```

The next milestone is therefore:

> **Turn the existing Brain library into an operable software-development platform.**

---

## 2. Product Vision

The system should not be designed as a coding agent. It should be designed as a persistent software-development brain.

Its long-term loop is:

```text
Observe the project
      ↓
Understand current state
      ↓
Understand requirement / task
      ↓
Determine relevant code and knowledge
      ↓
Construct exact task context
      ↓
Select executor
      ↓
Implement
      ↓
Verify independently
      ↓
Create pull request if policy allows
      ↓
Update project knowledge
      ↓
Publish meaningful observations to humans
      ↓
Observe again
```

Agents are workers inside this system, not the center of the architecture.

---

## 3. Core Architectural Principles

### 3.1 Brain-Owned Canonical Model

The Brain owns stable internal concepts:

```text
Project
Repository
Requirement
WorkItem
Document
DocumentVersion
DocumentNode
Decision
Domain
System
SoftwareComponent
Interface
Resource
Actor
ContextCapsule
Execution
Artifact
Evidence
VerificationResult
Observation
```

External products never become the domain model.

```text
OpenProject WorkPackage ─┐
Jira Issue ──────────────┼──> adapter ──> WorkItem
Linear Issue ────────────┘
```

The same applies to documentation and software catalogs.

### 3.2 Human Tools Are Interchangeable

Organizations should continue using the tools they already prefer.

Possible work-management providers:

```text
OpenProject
Jira
Linear
GitHub Issues
GitLab Issues
Azure DevOps
```

Possible documentation providers:

```text
XWiki
Confluence
TechDocs
Markdown in Git
Notion
SharePoint
```

Possible software catalogs:

```text
Backstage
ServiceNow
custom inventory
none
```

Possible source-control providers:

```text
GitLab
GitHub
Bitbucket
self-hosted Git
```

The Brain should use ports and adapters so that provider replacement does not affect planning, context construction, execution, or verification.

### 3.3 Optional Integrations Must Be Truly Optional

The Brain must support two valid operating modes.

Standalone:

```text
Git repository
+
Brain API
+
Internal WorkItems
+
Derived software topology
```

Integrated:

```text
OpenProject / Jira
+
XWiki / Confluence
+
Backstage if available
+
GitLab / GitHub
+
Brain
```

If OpenProject, XWiki, Backstage, or Docling is disabled, the Brain should still start and expose the capabilities that remain available.

### 3.4 Context Is a First-Class Product

The Brain should not solve context by sending a whole repository into the LLM.

It should construct the smallest sufficient context from:

```text
task
requirements
knowledge graph
code relation graph
software topology
semantic retrieval
lexical retrieval
architecture decisions
tests
git history
previous executions
verification feedback
```

This supports large frontier models, medium local models, and smaller models with smaller context windows.

### 3.5 Knowledge Is Version-Aware

A software fact must be scoped to the relevant repository state.

Example:

```text
AuthService.login
    CALLS
UserRepository.find_by_email
```

must carry enough revision metadata to know where it is valid:

```text
repository_id
branch
commit_sha
origin
confidence
```

### 3.6 Provenance Is Mandatory

The Brain distinguishes:

```text
DECLARED
    human-provided structured knowledge

DISCOVERED
    deterministic analysis

OBSERVED
    runtime / test evidence

INFERRED
    model-generated reasoning
```

Example:

```text
payment-service DEPENDS_ON redis

DECLARED: Backstage metadata
DISCOVERED: Redis client import
OBSERVED: runtime trace
INFERRED: LLM architecture reasoning
```

Conflicting evidence should be represented, not silently overwritten.

### 3.7 Verification Is Independent

A coding executor cannot decide that its own work is ready for pull request.

Default path:

```text
Implementation
      ↓
Deterministic checks
      ↓
Structural verification
      ↓
Semantic verification
      ↓
PR readiness gate
      ↓
Pull request
```

### 3.8 Important Observations Must Reach Humans

The Brain should not silently discover meaningful project information.

Examples:

```text
Existing implementation found.
Task is partially implemented.
Ticket scope differs from code reality.
Documentation conflicts with implementation.
An undocumented dependency was found.
Verification failed because one acceptance criterion is missing.
Human clarification is required.
Verification passed and PR is ready.
```

These should be stored canonically as `Observation` objects and, depending on policy, projected back into human tools as comments/activity.

---

## 4. Target Runtime Architecture

```text
                         HUMAN / EXTERNAL WORLD

 OpenProject / Jira        XWiki / Confluence       GitLab / GitHub
         │                         │                      │
         └─────────────────────────┼──────────────────────┘
                                   │
                            Adapter Gateway
                                   │
                     webhook / command / query
                                   │
                                   ▼
                            ┌─────────────┐
                            │  Brain API  │
                            │   FastAPI   │
                            └──────┬──────┘
                                   │
                           Application Layer
                                   │
                       Commands / Queries / Events
                                   │
                                   ▼
                         Workflow Orchestrator
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
          Ingestion            Planning            Execution
                                                       │
                                                       ▼
                                                  Verification
                                                       │
                                                       ▼
                                                    PR Gate
                                   │
                                   ▼
                         Canonical Brain State
                                   │
                    ┌──────────────┼───────────────┐
                    │              │               │
                PostgreSQL       Neo4j         Weaviate
                    │
                  Redis
                    │
                  MinIO
                                   │
                                   ▼
                         Observation Engine
                                   │
                         Human Activity Port
                                   │
                  ┌────────────────┼───────────────┐
                  ▼                ▼               ▼
             OpenProject          Jira          XWiki/etc.
              comment           comment          activity
```

---

## 5. Runtime Processes

The package should expose four primary executables.

### `brain-api`

FastAPI control plane.

Responsibilities:

```text
human commands
queries
webhook endpoints
health / readiness
capability discovery
workflow initiation
administrative APIs
```

It should never perform long-running repository indexing or coding synchronously.

### `brain-worker`

Executes asynchronous work:

```text
repository ingestion
document parsing
code indexing
knowledge projection
context construction
planning
coding execution
verification
external synchronization
```

Initially one worker process is sufficient.

### `brain-scheduler`

Periodic reconciliation process.

Responsibilities:

```text
check repository freshness
recover missed webhooks
refresh provider synchronization
detect stuck executions
check projection freshness
retry failed observation projections
```

### `brainctl`

Administrative/development CLI.

Examples:

```bash
brainctl status
brainctl capabilities
brainctl project create sample
brainctl repository add --project <id> ./sample_project
brainctl repository sync <repo-id>
brainctl context build <work-item-id> --budget 16000
brainctl work-item run <work-item-id>
brainctl execution verify <execution-id>
brainctl observation list
```

All four runtimes must use the same application services and composition root.

---

## 6. Composition Root

Recommended structure:

```text
brain/
├── bootstrap/
│   ├── container.py
│   ├── settings.py
│   ├── providers.py
│   ├── capabilities.py
│   └── lifecycle.py
```

Conceptual container:

```python
class BrainContainer:
    settings: BrainSettings

    state_repositories: StateRepositories
    graph: KnowledgeGraphRepository
    semantic_index: SemanticIndex
    event_bus: EventBus
    artifact_store: ArtifactStore

    work_management: WorkManagementPort
    documentation: list[DocumentationPort]
    software_catalog: SoftwareCatalogPort
    source_control: SourceControlPort
    document_conversion: DocumentConversionPort | None

    executor_registry: ExecutorRegistry

    project_service: ProjectService
    repository_service: RepositoryService
    ingestion_service: IngestionService
    context_service: ContextService
    planning_service: PlanningService
    execution_service: ExecutionService
    verification_service: VerificationService
    observation_service: ObservationService
```

Factory:

```python
async def create_brain_container(
    settings: BrainSettings,
) -> BrainContainer:
    ...
```

Every runtime uses this composition root.

Do not initialize provider clients at module import time.

---

## 7. Configuration Model

Configuration should express capabilities, not hard-code workflows to providers.

```yaml
brain:
  environment: development

storage:
  state:
    provider: postgres
    url: postgresql+asyncpg://postgres:postgres@postgres:5432/brain

  graph:
    provider: neo4j
    url: bolt://neo4j:7687

  semantic:
    provider: weaviate
    url: http://weaviate:8080

  queue:
    provider: redis
    url: redis://redis:6379

  artifacts:
    provider: minio

integrations:
  work_management:
    enabled: true
    provider: openproject
    required: false

  documentation:
    providers:
      - type: git
        enabled: true
      - type: xwiki
        enabled: false

  document_conversion:
    enabled: true
    provider: docling_serve
    required: false

  software_catalog:
    provider: derived
    external:
      type: backstage
      enabled: false

  source_control:
    provider: gitlab

executors:
  coding:
    provider: pi

automation:
  run_on_assignment: true
  auto_retry_verification_failure: true
  auto_create_pr: false

verification:
  require_pass_before_pr: true

human_approval:
  architecture_changes: true
  database_migrations: true
  security_sensitive_changes: true
  normal_code_changes: false
```

---

## 8. Capability Registry

At startup the Brain should explicitly report capability state.

Statuses:

```text
AVAILABLE
DEGRADED
DISABLED
UNAVAILABLE
MISCONFIGURED
```

Example:

```json
{
  "core": {
    "postgres": "AVAILABLE",
    "neo4j": "AVAILABLE",
    "weaviate": "AVAILABLE",
    "redis": "AVAILABLE"
  },
  "work_management": {
    "provider": "openproject",
    "status": "AVAILABLE"
  },
  "documentation": {
    "git": "AVAILABLE",
    "xwiki": "DISABLED"
  },
  "document_conversion": {
    "docling": "AVAILABLE"
  },
  "software_catalog": {
    "derived": "AVAILABLE",
    "backstage": "DISABLED"
  },
  "coding_executor": {
    "pi": "AVAILABLE"
  }
}
```

Expose:

```http
GET /api/v1/capabilities
```

Optional provider failure must not make the entire Brain unavailable unless configured as required.

---

## 9. Health Endpoints

### Liveness

```http
GET /health/live
```

Meaning: process is alive.

### Readiness

```http
GET /health/ready
```

Meaning: required Brain capabilities are available.

Optional OpenProject/XWiki/Backstage/Docling failures should appear in the capability endpoint instead of normally failing readiness.

---

## 10. Trigger Model

Every operation should record how it was triggered.

Canonical trigger types:

```text
USER
EVENT
SCHEDULED
INTERNAL
```

Different trigger sources must converge on the same application command.

Example:

```text
User:
POST /work-items/123/run
        ↓
RunWorkItemCommand

OpenProject:
Work item assigned to Brain actor
        ↓
WorkItemAssigned
        ↓
RunWorkItemCommand
```

After command creation, the orchestrator should not care about the source.

---

## 11. API Trigger Legend

```text
USER  = explicit human/API action
EVENT = external/internal event
BOTH  = either USER or EVENT
AGENT = callable by an executor as a Brain tool
```

---

## 12. System APIs

| Method | Endpoint | Purpose | Trigger |
|---|---|---|---|
| GET | `/health/live` | Liveness | USER/SYSTEM |
| GET | `/health/ready` | Readiness | USER/SYSTEM |
| GET | `/api/v1/capabilities` | Capabilities | USER |
| GET | `/api/v1/system/status` | Runtime status | USER |
| GET | `/api/v1/system/version` | Version/build | USER |
| POST | `/api/v1/system/reconcile` | Global reconciliation | USER/SCHEDULED |

---

## 13. Project APIs

| Method | Endpoint | Purpose | Trigger |
|---|---|---|---|
| POST | `/api/v1/projects` | Create project | USER |
| GET | `/api/v1/projects` | List projects | USER |
| GET | `/api/v1/projects/{id}` | Project state | USER |
| PATCH | `/api/v1/projects/{id}` | Update project | USER |
| POST | `/api/v1/projects/{id}/analyze` | Analyze project | BOTH |
| GET | `/api/v1/projects/{id}/topology` | Derived topology | USER |
| GET | `/api/v1/projects/{id}/knowledge-status` | Graph/index freshness | USER |

---

## 14. Repository APIs

| Method | Endpoint | Purpose | Trigger |
|---|---|---|---|
| POST | `/projects/{id}/repositories` | Register repository | USER |
| GET | `/repositories/{id}` | Repository state | USER |
| POST | `/repositories/{id}/sync` | Sync revision | BOTH |
| POST | `/repositories/{id}/ingest` | Analyze/index | BOTH |
| GET | `/repositories/{id}/status` | Ingestion status | USER |
| GET | `/repositories/{id}/changes` | Revision changes | USER |
| GET | `/repositories/{id}/symbols` | Symbol search | USER/AGENT |
| POST | `/repositories/{id}/impact-analysis` | Impact analysis | BOTH |

Push event flow:

```text
RepositoryRevisionChanged
        ↓
changed-file detection
        ↓
incremental code/docs ingestion
        ↓
code graph update
        ↓
knowledge graph update
        ↓
semantic index update
```

---

## 15. Document APIs

| Method | Endpoint | Purpose | Trigger |
|---|---|---|---|
| POST | `/projects/{id}/documents` | Register/upload document | USER |
| GET | `/documents/{id}` | Metadata | USER |
| GET | `/documents/{id}/versions` | History | USER |
| POST | `/documents/{id}/ingest` | Parse/index | BOTH |
| POST | `/documents/{id}/reprocess` | Force reprocessing | USER |
| GET | `/documents/{id}/structure` | Canonical structure | USER |
| GET | `/documents/{id}/knowledge` | Extracted knowledge | USER |

External document changes should normalize to `DocumentChanged`.

---

## 16. Requirement APIs

| Method | Endpoint | Purpose | Trigger |
|---|---|---|---|
| POST | `/requirements` | Create | USER |
| GET | `/requirements/{id}` | Retrieve | USER |
| PATCH | `/requirements/{id}` | Update | USER |
| POST | `/requirements/extract` | Extract from source | BOTH |
| POST | `/requirements/{id}/analyze` | Analyze ambiguity/state | BOTH |
| GET | `/requirements/{id}/coverage` | Implementation/test coverage | USER |
| GET | `/requirements/{id}/related-code` | Related implementation | USER/AGENT |

---

## 17. Work Item APIs

| Method | Endpoint | Purpose | Trigger |
|---|---|---|---|
| POST | `/work-items` | Create internal WorkItem | USER |
| GET | `/work-items/{id}` | Read | USER |
| PATCH | `/work-items/{id}` | Update | BOTH |
| POST | `/work-items/{id}/analyze` | Scope/status analysis | BOTH |
| POST | `/work-items/{id}/plan` | Create execution plan | BOTH |
| POST | `/work-items/{id}/context` | Build context | BOTH |
| POST | `/work-items/{id}/run` | Run engineering workflow | BOTH |
| POST | `/work-items/{id}/pause` | Pause | USER |
| POST | `/work-items/{id}/resume` | Resume | USER |
| POST | `/work-items/{id}/cancel` | Cancel | USER |
| POST | `/work-items/{id}/retry` | Retry | BOTH |
| GET | `/work-items/{id}/executions` | Execution history | USER |
| GET | `/work-items/{id}/observations` | Engineering journal | USER |

---

## 18. Context APIs

Context is a first-class product and should be inspectable.

| Method | Endpoint | Purpose | Trigger |
|---|---|---|---|
| POST | `/contexts/build` | Build context | BOTH |
| GET | `/contexts/{id}` | Retrieve capsule | USER/AGENT |
| GET | `/contexts/{id}/explanation` | Explain selection | USER |
| POST | `/contexts/{id}/expand` | Expand bounded context | BOTH/AGENT |
| POST | `/contexts/search` | Context-aware search | USER/AGENT |
| POST | `/contexts/symbol` | Symbol context | USER/AGENT |
| POST | `/contexts/related-files` | Related files | USER/AGENT |
| POST | `/contexts/related-tests` | Related tests | USER/AGENT |

---

## 19. Code Intelligence APIs

| Method | Endpoint | Purpose | Trigger |
|---|---|---|---|
| GET | `/code/symbols/{id}` | Symbol detail | USER/AGENT |
| GET | `/code/symbols/{id}/callers` | Reverse calls | USER/AGENT |
| GET | `/code/symbols/{id}/callees` | Outgoing calls | USER/AGENT |
| GET | `/code/symbols/{id}/tests` | Related tests | USER/AGENT |
| POST | `/code/search` | Code/symbol search | USER/AGENT |
| POST | `/code/impact` | Impact analysis | BOTH |
| GET | `/code/files/{id}/dependencies` | File dependencies | USER/AGENT |

---

## 20. Knowledge APIs

| Method | Endpoint | Purpose | Trigger |
|---|---|---|---|
| POST | `/knowledge/search` | Hybrid knowledge retrieval | USER/AGENT |
| GET | `/knowledge/entities/{id}` | Entity | USER |
| GET | `/knowledge/entities/{id}/relations` | Relations | USER |
| POST | `/knowledge/traverse` | Graph traversal | USER/AGENT |
| GET | `/knowledge/conflicts` | Conflicting knowledge | USER |
| POST | `/knowledge/conflicts/{id}/resolve` | Resolve conflict | USER |

---

## 21. Execution APIs

| Method | Endpoint | Purpose | Trigger |
|---|---|---|---|
| POST | `/executions` | Start lower-level execution | BOTH |
| GET | `/executions/{id}` | Status | USER |
| POST | `/executions/{id}/cancel` | Cancel | USER |
| POST | `/executions/{id}/retry` | Retry | BOTH |
| GET | `/executions/{id}/artifacts` | Artifacts | USER |
| GET | `/executions/{id}/evidence` | Evidence | USER |
| GET | `/executions/{id}/diff` | Git diff | USER |

---

## 22. Verification APIs

| Method | Endpoint | Purpose | Trigger |
|---|---|---|---|
| POST | `/executions/{id}/verify` | Verify implementation | BOTH |
| GET | `/verifications/{id}` | Verification report | USER |
| POST | `/verifications/{id}/rerun` | Reverify | BOTH |
| GET | `/verifications/{id}/evidence` | Evidence | USER |
| GET | `/verifications/{id}/failures` | Structured failures | USER |

Normally `ExecutionCompleted` automatically emits `VerificationRequested`.

---

## 23. Pull Request APIs

| Method | Endpoint | Purpose | Trigger |
|---|---|---|---|
| POST | `/executions/{id}/pull-request` | Create PR/MR | BOTH |
| GET | `/pull-requests/{id}` | PR state | USER |
| POST | `/pull-requests/{id}/refresh` | Sync state | BOTH |

Default:

```text
Verification PASS
      ↓
PRReadinessPassed
      ↓
auto-create allowed?
   /          \
 yes          no
  │            │
Create PR   Observation / wait
```

Merge should remain human-controlled by default.

---

## 24. Observation Domain

Suggested canonical model:

```python
class Observation(BaseModel):
    id: UUID
    project_id: UUID
    work_item_id: UUID | None
    execution_id: UUID | None

    observation_type: ObservationType
    severity: ObservationSeverity
    visibility: ObservationVisibility

    title: str
    body: str

    source: str
    evidence_refs: list[UUID]
    requires_human_attention: bool
    created_at: datetime
```

Types:

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

Visibility:

```text
INTERNAL
TEAM
IMPORTANT
```

---

## 25. Observation APIs

| Method | Endpoint | Purpose | Trigger |
|---|---|---|---|
| GET | `/observations` | Search journal | USER |
| GET | `/work-items/{id}/observations` | Task observations | USER |
| POST | `/observations/{id}/acknowledge` | Acknowledge | USER |
| POST | `/observations/{id}/resolve` | Resolve | USER |
| POST | `/work-items/{id}/feedback` | Human feedback | USER/EVENT |

---

## 26. Observation Projection to Human Tools

Workflow nodes must never call Jira/OpenProject directly.

Correct path:

```text
Verification / Planning / Analysis
        ↓
ObservationCreated
        ↓
ObservationProjectionService
        ↓
HumanActivityPort
        ↓
OpenProject / Jira / GitHub / etc.
```

Port:

```python
class HumanActivityPort(Protocol):
    async def publish_observation(
        self,
        target: ExternalReference,
        observation: Observation,
    ) -> None:
        ...
```

Implementations may include:

```text
OpenProjectActivityAdapter
JiraCommentAdapter
GitHubIssueCommentAdapter
GitLabIssueCommentAdapter
XWikiActivityAdapter
ConfluenceCommentAdapter
```

Projection should be idempotent and track external comment IDs.

---

## 27. Observation Noise Policy

Do **not** publish these to humans:

```text
file parsed
embedding stored
graph edge inserted
context candidate score
worker heartbeat
```

Do publish meaningful engineering observations:

```text
partial implementation discovered
unexpected dependency discovered
documentation/code conflict
verification failure
architecture violation
human decision required
verification pass
external task says Done but technical verification failed
```

---

## 28. Example Observation Messages

### Existing implementation

> **Brain observation — existing implementation found**  
> Login-attempt tracking already exists in `AuthenticationService`. The remaining scope appears to be account-lock enforcement and related tests.

### Verification failure

> **Verification failed**  
> Existing tests pass, but acceptance criterion 2 is not satisfied: a successful login does not reset the failed-attempt counter. The implementation will be retried with this feedback.

### Human input required

> **Human input required**  
> The requirement does not specify whether account locks expire automatically or require administrator action. Automation is paused until this is clarified.

### Documentation conflict

> **Brain observation — documentation conflict**  
> Architecture documentation states that authentication state is stored only in PostgreSQL, but the current implementation also uses Redis. Both facts were preserved and the documentation has been marked potentially stale.

### Verification passed

> **Verification passed**  
> Configured checks passed and the implementation satisfies the current acceptance criteria. The change is ready for pull-request creation.

---

## 29. Activity vs Observation vs Decision

Keep them distinct.

```text
Activity
    lifecycle fact
    "Execution started"

Observation
    meaningful engineering finding
    "Existing implementation discovered"

Decision
    lasting engineering choice
    "Use Redis for lockout counters"
```

Activities are usually internal.

Important Observations may be projected to human tools.

Decisions become long-term knowledge and may optionally be projected into documentation.

---

## 30. Human Feedback Loop

A human reply in OpenProject/Jira/XWiki should be normalized to:

```text
HumanFeedbackReceived
```

Then:

```text
HumanFeedbackReceived
        ↓
store feedback
        ↓
update requirement / decision if appropriate
        ↓
invalidate stale context
        ↓
rebuild context
        ↓
resume workflow
```

---

## 31. External Event Triggers

| External Event | Brain Action |
|---|---|
| Repository push | Incremental code/docs ingestion |
| Branch/revision changed | Revision state update |
| PR/MR updated | Reverification if relevant |
| PR merged | Re-ingest resulting revision |
| Work item created | Import/sync |
| Work item changed | Re-evaluate related state |
| Work item assigned to Brain actor | Start workflow if policy permits |
| Work item comment added | HumanFeedbackReceived |
| Acceptance criteria changed | Re-plan/rebuild context |
| Documentation changed | Re-ingest |
| Catalog changed | Reconcile topology |
| CI completed | Store verification evidence |
| Runtime telemetry imported | Update observed graph |

---

## 32. Internal Events

```text
ProjectCreated
RepositoryRegistered
RepositoryRevisionChanged
RepositoryIngested
DocumentChanged
DocumentIngested
TopologyUpdated
CodeGraphUpdated
KnowledgeUpdated
WorkItemCreated
WorkItemChanged
WorkItemAssigned
ContextBuilt
ExecutionRequested
ExecutionStarted
ExecutionCompleted
ExecutionFailed
VerificationRequested
VerificationFailed
VerificationPassed
ObservationCreated
ObservationProjected
ObservationProjectionFailed
HumanFeedbackReceived
ApprovalRequested
PRReadinessPassed
PullRequestCreated
PullRequestMerged
KnowledgeConflictDetected
```

---

## 33. Orchestration Architecture

Do not build one huge graph.

Use bounded workflows:

```text
                     Engineering Orchestrator

                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
      Ingestion           Planning           Work Execution
                                                  │
                                                  ▼
                                             Verification
                                                  │
                                                  ▼
                                                PR Flow
```

---

## 34. Main Work-Item Orchestrator

```text
START
  ↓
LOAD WORK ITEM
  ↓
SYNC CURRENT PROJECT STATE
  ↓
UNDERSTAND REQUIREMENT
  ↓
ANALYZE IMPLEMENTATION STATUS
  ↓
CREATE OBSERVATION IF MEANINGFUL
  ↓
BUILD TASK-SPECIFIC CONTEXT
  ↓
ASSESS COMPLEXITY / RISK
  ↓
SELECT EXECUTOR
  ↓
APPROVAL REQUIRED?
 ┌──────────────┐
 │ yes          │ no
 ▼              │
WAIT FOR HUMAN  │
 └──────┬───────┘
        ▼
     EXECUTE
        ↓
COLLECT ARTIFACTS / EVIDENCE
        ↓
     VERIFY
        ↓
 ┌──────┼───────────┐
 │      │           │
PASS   FAIL      BLOCKED
 │      │           │
 │      ▼           ▼
 │  OBSERVATION  OBSERVATION
 │      │           │
 │   retry?      HUMAN INPUT
 │   /   \
 │ yes   no
 │  │     │
 │  └──→ EXECUTE / HUMAN
 │
 ▼
PR READINESS
  ↓
AUTO PR ALLOWED?
 /            \
yes            no
 │              │
CREATE PR    OBSERVATION
 │              │
 └───────┬──────┘
         ▼
UPDATE HUMAN TOOL
         ↓
UPDATE BRAIN KNOWLEDGE
         ↓
COMPLETE
```

---

## 35. Orchestrator State

Graph state should contain references, not large content.

```python
class EngineeringWorkflowState(TypedDict):
    workflow_id: UUID
    project_id: UUID
    work_item_id: UUID
    repository_id: UUID | None
    base_revision: str | None
    context_capsule_id: UUID | None
    execution_id: UUID | None
    verification_id: UUID | None
    stage: str
    retry_count: int
    waiting_for_human: bool
    correlation_id: UUID
```

Do not place:

```text
whole repository
full source files
large documents
entire context capsule
full model conversation
```

inside orchestration state.

---

## 36. Orchestrator Node Rule

Bad:

```text
Graph node
  → queries Neo4j directly
  → queries Weaviate directly
  → calls OpenProject directly
  → calls model directly
```

Good:

```text
Graph node
      ↓
Application Service
      ↓
Port
      ↓
Adapter
```

LangGraph coordinates; application services perform work.

---

## 37. Worker Model

Long-running endpoint:

```text
POST /work-items/{id}/run
        ↓
202 Accepted
        ↓
RunWorkItemCommand
        ↓
queue / event bus
        ↓
brain-worker
        ↓
workflow
```

FastAPI should not wait for coding, ingestion, or verification to finish.

---

## 38. Scheduler / Reconciliation

The scheduler should periodically answer:

```text
Did repository HEAD change?
Was a webhook missed?
Is external work state stale?
Did documentation change?
Is Neo4j projection behind PostgreSQL?
Is Weaviate behind canonical versions?
Is an execution stuck?
Did a PR merge without re-ingestion?
Did observation projection fail?
```

Webhooks provide low latency.

Reconciliation provides eventual consistency.

---

## 39. Reference Deployment

### Core Brain services

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

These form the Brain platform.

### Optional reference integrations

```text
OpenProject
XWiki
Docling Serve
Backstage
GitLab
llama.cpp
Pi
```

These are integration/reference environment components, not universal mandatory production dependencies.

---

## 40. Compose Layout

Recommended:

```text
deploy/
├── compose.yaml
├── compose.openproject.yaml
├── compose.xwiki.yaml
├── compose.docling.yaml
├── compose.backstage.yaml
├── compose.gitlab.yaml
└── env/
    ├── brain.env.example
    ├── openproject.env.example
    ├── xwiki.env.example
    └── backstage.env.example
```

Core:

```bash
docker compose up -d
```

Reference environment can combine overlays or profiles.

---

## 41. Docling Role

Docling is a document-conversion capability, not primarily a human collaboration tool.

Canonical port:

```text
DocumentConversionPort
```

Implementations:

```text
DoclingServeAdapter
LocalDoclingAdapter
NativeStructuredParserAdapter
```

If Docling is disabled, Markdown/OpenAPI/YAML/JSON/source parsing should continue. Only formats that require conversion should report the capability as unavailable.

---

## 42. OpenProject / Jira Role

Canonical port:

```text
WorkManagementPort
```

Implementations:

```text
InternalWorkManagementAdapter
OpenProjectAdapter
JiraAdapter
GitHubIssuesAdapter
```

Internal WorkItems are important because the Brain must remain operable without an external project-management system.

---

## 43. XWiki / Confluence Role

Canonical port:

```text
DocumentationPort
```

Implementations:

```text
GitDocumentationAdapter
XWikiAdapter
ConfluenceAdapter
```

External wiki systems enrich Brain knowledge. Git documentation remains a valid source even when they are absent.

---

## 44. Backstage Role

Canonical port:

```text
SoftwareCatalogPort
```

Implementations:

```text
DerivedSoftwareCatalog
BackstageCatalogAdapter
FutureCatalogAdapter
```

The default should be derived topology.

The Brain can discover topology from:

```text
repository boundaries
manifests
Dockerfiles
Compose
Kubernetes
Terraform
OpenAPI
source dependencies
runtime evidence
```

When Backstage is present, declared and discovered topology are reconciled.

---

## 45. Pi / Coding Agent Role

Pi should remain behind `ExecutorPort`.

Brain owns:

```text
task
context
permissions
workspace
execution identity
verification
history
observations
PR readiness
```

Pi owns:

```text
LLM loop
tool calls
file edits
shell interaction
short-term execution session
```

This keeps Pi replaceable.

---

## 46. Pull Request Policy

Default:

```text
coding complete
      ↓
verification
      ↓
PASS
      ↓
PR readiness
      ↓
PR creation
```

No coding executor should bypass verification unless a special explicit policy allows it.

---

## 47. Example Complete Flow

Task:

```text
Implement account locking after five failed login attempts.
```

Flow:

```text
OpenProject assigns task to Brain actor
        ↓
WorkItemAssigned
        ↓
RunWorkItemCommand
        ↓
load canonical WorkItem
        ↓
link requirement
        ↓
analyze implementation status
        ↓
existing login-attempt tracking discovered
        ↓
ObservationCreated
        ↓
OpenProject comment published
        ↓
impact analysis
        ↓
Context Capsule
        ↓
executor selected
        ↓
Pi receives bounded context
        ↓
isolated worktree
        ↓
implementation
        ↓
verification
        ↓
FAIL: successful login does not reset counter
        ↓
ObservationCreated + OpenProject comment
        ↓
retry context includes verification feedback
        ↓
Pi retries
        ↓
verification PASS
        ↓
ObservationCreated
        ↓
PR created if policy allows
        ↓
PR linked to work item
        ↓
merge occurs later
        ↓
new revision ingested
        ↓
code graph updated
        ↓
knowledge graph updated
        ↓
semantic index updated
        ↓
Brain now understands current implementation
```

---

## 48. Recommended Runtime Package Structure

```text
brain/
├── bootstrap/
│   ├── container.py
│   ├── settings.py
│   ├── providers.py
│   ├── capabilities.py
│   └── lifecycle.py
│
├── api/
│   ├── app.py
│   ├── runner.py
│   ├── lifespan.py
│   ├── dependencies.py
│   ├── schemas/
│   └── routes/
│       ├── health.py
│       ├── capabilities.py
│       ├── projects.py
│       ├── repositories.py
│       ├── documents.py
│       ├── requirements.py
│       ├── work_items.py
│       ├── contexts.py
│       ├── code.py
│       ├── knowledge.py
│       ├── executions.py
│       ├── verification.py
│       ├── observations.py
│       └── webhooks.py
│
├── workers/
│   ├── main.py
│   ├── dispatcher.py
│   ├── ingestion.py
│   ├── planning.py
│   ├── execution.py
│   ├── verification.py
│   └── sync.py
│
├── scheduler/
│   ├── main.py
│   ├── jobs.py
│   └── reconciliation.py
│
├── cli/
│   └── main.py
│
├── orchestration/
│   ├── engineering_workflow.py
│   ├── ingestion_workflow.py
│   ├── planning_workflow.py
│   ├── verification_workflow.py
│   └── states.py
│
├── observations/
│   ├── models.py
│   ├── service.py
│   ├── policy.py
│   └── projection.py
│
└── integrations/
    ├── human_activity/
    ├── work_management/
    ├── documentation/
    ├── software_catalog/
    ├── source_control/
    └── document_conversion/
```

---

## 49. Executable Entry Points

Recommended `pyproject.toml`:

```toml
[project.scripts]
brain-api = "brain.api.runner:main"
brain-worker = "brain.workers.main:main"
brain-scheduler = "brain.scheduler.main:main"
brainctl = "brain.cli.main:main"
```

One Docker image can run different commands.

---

## 50. Full Reference Environment Acceptance Test

The environment should prove:

```text
1. Start Brain core.
2. Start OpenProject.
3. Start XWiki.
4. Start Docling Serve.
5. Optionally start Backstage.
6. Register project.
7. Register Git repository.
8. Ingest README, architecture docs, source and tests.
9. Ingest PDF specification through Docling.
10. Import/sync OpenProject task.
11. Analyze implementation status.
12. Publish meaningful observation if scope differs.
13. Build task-specific context.
14. Execute through Pi.
15. Verify independently.
16. Publish failed-verification observation if needed.
17. Retry.
18. Verification passes.
19. Create PR/MR.
20. Publish PR observation into OpenProject.
21. Merge PR.
22. Re-ingest resulting revision.
23. Update code graph.
24. Update knowledge graph.
25. Update semantic index.
26. Brain reports the new implementation state correctly.
```

---

## 51. Definition of an Operable Brain

The Brain is operational when:

- FastAPI starts from one composition root;
- required core dependencies report readiness;
- optional integrations report capability status;
- a project can be created without OpenProject/Jira;
- a repository can be registered and synchronized;
- ingestion runs asynchronously;
- a WorkItem can be created internally or imported externally;
- context can be built and inspected;
- coding can run through a replaceable executor;
- verification gates PR creation;
- observations are stored canonically;
- important observations can be published into configured human tools;
- human replies can return as `HumanFeedbackReceived`;
- workflows recover after interruption;
- external tools can be disabled or replaced without changing core application services.

---

## 52. Final Dependency Rule

Always preserve:

```text
Human Tools / Providers
        ↓
Adapters
        ↓
Canonical Commands / Events
        ↓
Application Services
        ↓
Domain / Brain
        ↓
Ports
        ↓
Infrastructure Implementations
```

Never:

```text
Brain domain
    ↓
Jira / OpenProject / XWiki / Backstage / Pi-specific models
```

The Brain should behave like a software-engineering participant that **observes, understands, plans, executes, verifies, explains, and updates**, while remaining independent of the tools an organization chooses to use.
