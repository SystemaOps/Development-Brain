# Software Development Brain — Phase-by-Phase Coding Plan

> Detailed implementation plan for a coding agent building the Software Development Brain incrementally, with stable architecture boundaries, testable deliverables, and explicit completion gates for every phase.

---

# Table of Contents

1. [Purpose](#1-purpose)
2. [Implementation Principles](#2-implementation-principles)
3. [Execution Strategy for the Coding Agent](#3-execution-strategy-for-the-coding-agent)
4. [Phase Overview](#4-phase-overview)
5. [Phase 0 — Repository Assessment and Architecture Baseline](#5-phase-0--repository-assessment-and-architecture-baseline)
6. [Phase 1 — Canonical Domain Model and Core Contracts](#6-phase-1--canonical-domain-model-and-core-contracts)
7. [Phase 2 — PostgreSQL State Layer and Persistence Contracts](#7-phase-2--postgresql-state-layer-and-persistence-contracts)
8. [Phase 3 — Event Model and Workflow Foundation](#8-phase-3--event-model-and-workflow-foundation)
9. [Phase 4 — Repository Registration and Source-Control Foundation](#9-phase-4--repository-registration-and-source-control-foundation)
10. [Phase 5 — Document Ingestion and Canonical Documentation Model](#10-phase-5--document-ingestion-and-canonical-documentation-model)
11. [Phase 6 — Software Topology Discovery](#11-phase-6--software-topology-discovery)
12. [Phase 7 — Code Intelligence and Code Relation Graph](#12-phase-7--code-intelligence-and-code-relation-graph)
13. [Phase 8 — Neo4j Knowledge Graph](#13-phase-8--neo4j-knowledge-graph)
14. [Phase 9 — Weaviate Semantic Index and Hybrid Retrieval](#14-phase-9--weaviate-semantic-index-and-hybrid-retrieval)
15. [Phase 10 — Context Engine and Context Capsules](#15-phase-10--context-engine-and-context-capsules)
16. [Phase 11 — Planning and Implementation-Status Intelligence](#16-phase-11--planning-and-implementation-status-intelligence)
17. [Phase 12 — Executor Abstraction and Pi Coding-Agent Integration](#17-phase-12--executor-abstraction-and-pi-coding-agent-integration)
18. [Phase 13 — Verification Engine and PR Readiness Gate](#18-phase-13--verification-engine-and-pr-readiness-gate)
19. [Phase 14 — Work-Management Integration](#19-phase-14--work-management-integration)
20. [Phase 15 — Documentation and Catalog Integrations](#20-phase-15--documentation-and-catalog-integrations)
21. [Phase 16 — LangGraph Workflow Orchestration and Checkpointing](#21-phase-16--langgraph-workflow-orchestration-and-checkpointing)
22. [Phase 17 — Human-in-the-Loop, Policies, and Permissions](#22-phase-17--human-in-the-loop-policies-and-permissions)
23. [Phase 18 — Observability, Metrics, and Context-Quality Evaluation](#23-phase-18--observability-metrics-and-context-quality-evaluation)
24. [Phase 19 — Runtime Intelligence and Advanced Verification](#24-phase-19--runtime-intelligence-and-advanced-verification)
25. [Phase 20 — Optimization, Model Routing, and Learning](#25-phase-20--optimization-model-routing-and-learning)
26. [Cross-Phase Testing Requirements](#26-cross-phase-testing-requirements)
27. [Definition of Done for the Full System](#27-definition-of-done-for-the-full-system)
28. [Recommended First Milestone](#28-recommended-first-milestone)

---

# 1. Purpose

This document converts the Software Development Brain architecture into an actionable coding plan.

The plan is designed so that a coding agent can execute the work incrementally without losing the architectural principles established for the system.

The system being built is not merely a coding agent.

It is a persistent, version-aware software-development brain that:

- understands projects,
- understands requirements,
- understands architecture,
- understands source code,
- tracks tasks,
- builds code and knowledge relationships,
- constructs precise context for the current task,
- selects an executor,
- verifies generated changes,
- and updates its project knowledge after every execution.

The coding agent implementing this system must follow the phases in order unless a task explicitly states that it can be executed independently.

The most important implementation rule is:

> **Do not allow an external tool, database, workflow engine, or coding agent to become the domain model of the system.**

OpenProject, Jira, XWiki, Confluence, Backstage, Pi, PostgreSQL, Neo4j, Weaviate, Redis, GitLab, and LangGraph are implementations behind stable contracts.

---

# 2. Implementation Principles

Every phase must preserve the following principles.

## 2.1 Brain-Owned Canonical Identity

All important entities must receive internal IDs.

Examples:

```text
project_id
repository_id
work_item_id
requirement_id
document_id
execution_id
artifact_id
evidence_id
verification_id
actor_id
```

External IDs such as:

```text
JIRA-123
OpenProject WorkPackage 982
Confluence page 18722
GitLab issue 51
```

must be stored only as external references.

---

## 2.2 Ports and Adapters

Core application services must depend on interfaces, not providers.

Example:

```text
WorkManagementPort
    ├── OpenProjectAdapter
    └── JiraAdapter
```

The core must never contain business logic that depends directly on:

```text
OpenProjectWorkPackage
JiraIssue
ConfluencePage
BackstageEntity
```

---

## 2.3 Version-Aware Knowledge

Source-code and documentation knowledge must carry revision information where applicable.

At minimum:

```text
repository_id
branch
commit_sha
source_path
content_hash
```

---

## 2.4 Provenance

Knowledge must distinguish:

```text
DECLARED
DISCOVERED
OBSERVED
INFERRED
```

LLM-generated relations must never be stored as if they were deterministic facts.

---

## 2.5 Context Is Constructed

Do not implement a "send the whole repository" workflow.

Context must be built from:

```text
task
requirements
knowledge graph
code graph
semantic retrieval
repository structure
history
tests
architecture
verification feedback
```

---

## 2.6 Verification Is Independent

The coding executor must not decide that its own result is ready for pull request.

Verification must happen in a separate stage.

---

## 2.7 Small Models Are First-Class

Context construction must support narrow token budgets.

Every context-building API should accept an explicit budget.

---

## 2.8 Incremental Processing

Document and code ingestion should update changed artifacts instead of rebuilding the entire project after every change.

---

## 2.9 Evidence Before Claims

Whenever possible, store:

```text
test result
git diff
build output
lint result
static analysis
verification report
runtime observation
```

rather than a natural-language claim alone.

---

# 3. Execution Strategy for the Coding Agent

The coding agent implementing this plan should follow these rules for every task.

## Before Starting a Task

The agent must:

1. inspect existing implementation;
2. identify affected modules;
3. identify relevant tests;
4. check whether equivalent functionality already exists;
5. preserve public contracts unless the task explicitly changes them;
6. avoid broad unrelated refactoring;
7. document important design decisions.

## During Implementation

The agent must:

1. keep implementation small and composable;
2. use typed models;
3. prefer protocols/interfaces at boundaries;
4. add tests together with implementation;
5. avoid provider-specific types inside domain/application layers;
6. preserve backwards compatibility where reasonable.

## Before Completing a Task

The agent must run:

```text
unit tests
relevant integration tests
type checking
linting
format checks
```

where available.

Each task should end with:

```text
Implementation summary
Files changed
Tests added
Tests executed
Known limitations
Follow-up tasks
```

---

# 4. Phase Overview

```text
Phase 0   Repository Assessment
Phase 1   Canonical Domain Model
Phase 2   PostgreSQL Persistence
Phase 3   Events + Workflow Foundation
Phase 4   Repository + Git Foundation
Phase 5   Document Ingestion
Phase 6   Software Topology Discovery
Phase 7   Code Intelligence
Phase 8   Neo4j Knowledge Graph
Phase 9   Weaviate + Hybrid Retrieval
Phase 10  Context Engine
Phase 11  Planning Intelligence
Phase 12  Executor + Pi Integration
Phase 13  Verification + PR Gate
Phase 14  Work-Management Integration
Phase 15  Documentation + Catalog Integration
Phase 16  LangGraph Orchestration
Phase 17  Human Approval + Security Policies
Phase 18  Observability + Context Metrics
Phase 19  Runtime Intelligence
Phase 20  Model Routing + Optimization
```

The key dependency chain is:

```text
Domain
 ↓
Persistence
 ↓
Ingestion
 ↓
Code/Knowledge Intelligence
 ↓
Context
 ↓
Planning/Execution
 ↓
Verification
 ↓
Human Tool Integrations
 ↓
Optimization
```

---

# 5. Phase 0 — Repository Assessment and Architecture Baseline

## Goal

Understand the existing repository before modifying it and create an architectural baseline.

No large implementation work should happen in this phase.

---

## Task 0.1 — Inventory Existing Repository

### Actions

Inspect:

```text
infra/
planning_agent_core/
sample_project/
tests/
configuration files
Docker Compose files
LangGraph usage
PostgreSQL setup
Neo4j setup
Weaviate setup
Redis setup
OpenProject integration
agent contracts
existing skills
```

### Produce

Create:

```text
docs/architecture/current-state.md
```

Include:

- existing packages;
- existing domain models;
- current agent contracts;
- current persistence models;
- current workflow;
- existing integrations;
- implemented skills;
- missing skills;
- architectural coupling problems;
- duplicated models;
- dead/obsolete modules.

### Acceptance Criteria

- Existing repository structure is documented.
- No existing major component is accidentally replaced without understanding it.
- Existing APIs/contracts that need migration are listed.

---

## Task 0.2 — Produce Architecture Gap Analysis

Compare the current system against the target architecture.

Classify each capability:

```text
AVAILABLE
PARTIAL
MISSING
NEEDS_REFACTOR
DEPRECATED
```

Capabilities:

```text
canonical domain
document ingestion
code intelligence
knowledge graph
semantic retrieval
context engine
planning
executor abstraction
verification
OpenProject adapter
Git integration
LangGraph checkpointing
```

### Deliverable

```text
docs/architecture/gap-analysis.md
```

---

## Task 0.3 — Define Dependency Rules

Create an architectural dependency policy.

Target:

```text
domain
    depends on nothing infrastructure-specific

application/services
    depends on domain + ports

adapters
    depend on ports + provider SDK

infrastructure
    implements ports

api
    calls application services

workers
    call application services
```

Optional enforcement:

- import-linter;
- pytest architecture tests;
- custom AST checks.

### Acceptance Criteria

Provider modules cannot be imported by domain modules.

---

## Phase 0 Completion Gate

Do not continue until:

- existing implementation is understood;
- migrations are identified;
- architecture boundaries are written down.

---

# 6. Phase 1 — Canonical Domain Model and Core Contracts

## Goal

Create the stable conceptual model of the brain before connecting databases, agents, or external tools.

---

## Task 1.1 — Create Core Identity Types

Implement strong IDs or typed UUID wrappers where practical:

```text
ProjectId
RepositoryId
WorkItemId
RequirementId
DocumentId
DocumentVersionId
ActorId
ExecutionId
ArtifactId
EvidenceId
DecisionId
VerificationId
ContextCapsuleId
WorkflowId
```

### Requirements

- Generate internal IDs independently of providers.
- Serialize cleanly through Pydantic.
- Support PostgreSQL UUID columns.

---

## Task 1.2 — ExternalReference Model

Implement:

```python
class ExternalReference(BaseModel):
    provider: str
    external_id: str
    external_type: str | None
    url: str | None
    namespace: str | None
```

### Tests

Verify mappings for:

```text
OpenProject
Jira
GitLab
GitHub
Confluence
XWiki
Backstage
```

without creating provider-specific domain types.

---

## Task 1.3 — Project Domain

Implement:

```text
Project
Repository
Actor
```

Include lifecycle/status enums.

### Acceptance Criteria

A project can exist without any external project-management provider.

---

## Task 1.4 — WorkItem Domain

Implement:

```text
WorkItem
WorkItemType
WorkItemStatus
Priority
Assignment
AcceptanceCriterion
```

Recommended types:

```text
EPIC
FEATURE
STORY
TASK
BUG
INVESTIGATION
REFACTORING
VERIFICATION
DOCUMENTATION
OPERATIONS
```

### Important

Separate:

```text
human_work_status
implementation_status
verification_status
pull_request_status
```

Do not collapse these into one status.

---

## Task 1.5 — Requirement Domain

Implement:

```text
Requirement
RequirementStatus
RequirementSource
AcceptanceCriterion
Constraint
```

Support:

```text
requirement hierarchy
parent requirement
derived requirement
related work items
```

---

## Task 1.6 — Documentation Domain

Implement:

```text
Document
DocumentVersion
DocumentNode
DocumentSource
```

DocumentNode fields should support:

```text
heading path
semantic node type
parent
children
links
code references
requirement references
task references
```

---

## Task 1.7 — Software Model

Implement canonical:

```text
Domain
System
SoftwareComponent
Interface
Resource
```

These must not depend on Backstage.

---

## Task 1.8 — Engineering History Domain

Implement:

```text
Decision
Execution
Artifact
Evidence
VerificationResult
```

---

## Task 1.9 — Knowledge Provenance Types

Implement:

```text
KnowledgeOrigin
KnowledgeEvidence
KnowledgeConfidence
RevisionScope
```

Origins:

```text
DECLARED
DISCOVERED
OBSERVED
INFERRED
```

---

## Task 1.10 — Define Core Ports

Create Protocol interfaces for:

```text
WorkManagementPort
DocumentationPort
SoftwareCatalogPort
SourceControlPort
PullRequestPort
CIValidationPort
ExecutorPort

ProjectRepository
WorkItemRepository
RequirementRepository
DocumentRepository
ExecutionRepository

KnowledgeGraphRepository
SemanticIndex
CheckpointStore
ArtifactStore
EventBus
```

No implementation yet beyond test fakes.

---

## Task 1.11 — In-Memory Reference Implementations

Create lightweight in-memory adapters for important ports.

Purpose:

- test application services without PostgreSQL/Neo4j/Weaviate;
- establish contract behavior.

---

## Task 1.12 — Contract Test Framework

Create common tests that future adapters must pass.

Examples:

```text
WorkItemRepositoryContract
DocumentationPortContract
SemanticIndexContract
KnowledgeGraphRepositoryContract
ExecutorPortContract
```

---

## Phase 1 Completion Gate

Must be possible to model:

```text
Project
 ↓
Requirement
 ↓
WorkItem
 ↓
Execution
 ↓
Artifact + Evidence
 ↓
Verification
```

without importing:

```text
OpenProject
Jira
Neo4j
Weaviate
Pi
LangGraph
```

---

# 7. Phase 2 — PostgreSQL State Layer and Persistence Contracts

## Goal

Establish PostgreSQL as the durable transactional source of truth.

---

## Task 2.1 — Database Infrastructure

Implement:

- connection configuration;
- SQLAlchemy/SQLModel or selected ORM;
- migrations;
- transaction/session management;
- repository factory.

### Requirements

Support:

```text
local development
test database
container deployment
```

---

## Task 2.2 — Core Tables

Implement tables for:

```text
projects
repositories
actors
work_items
requirements
documents
document_versions
document_nodes
decisions
executions
artifacts
evidence
verification_results
external_references
```

---

## Task 2.3 — Revision and Provenance Persistence

Persist:

```text
commit_sha
branch
source path
content hash
knowledge origin
confidence
discovery method
timestamps
```

---

## Task 2.4 — Repository Implementations

Implement PostgreSQL versions of:

```text
ProjectRepository
RepositoryRepository
WorkItemRepository
RequirementRepository
DocumentRepository
ExecutionRepository
DecisionRepository
EvidenceRepository
```

---

## Task 2.5 — Transaction Boundaries

Create explicit Unit of Work or transaction service.

Example operations that should be atomic:

```text
create execution + associate context
save verification + evidence
ingest document version + mark current
sync external work item + external ref
```

---

## Task 2.6 — Migration Tests

Automated test:

```text
empty DB
 ↓
latest migration
 ↓
schema valid
```

Also test migration downgrade if project policy requires it.

---

## Task 2.7 — Persistence Contract Tests

Run the same repository contract tests against:

```text
in-memory implementation
PostgreSQL implementation
```

---

## Phase 2 Completion Gate

The brain must be restart-safe for all canonical transactional entities.

---

# 8. Phase 3 — Event Model and Workflow Foundation

## Goal

Normalize provider events and internal lifecycle changes before adding orchestration complexity.

---

## Task 3.1 — EventEnvelope

Implement:

```text
event_id
event_type
project_id
occurred_at
correlation_id
causation_id
source
payload
```

---

## Task 3.2 — Canonical Event Types

Define models for:

```text
ProjectCreated
RepositoryRegistered
RepositoryRevisionChanged
DocumentChanged
WorkItemCreated
WorkItemChanged
WorkItemAssigned
RequirementChanged

ExecutionRequested
ExecutionStarted
ExecutionCompleted

VerificationRequested
VerificationCompleted

PullRequestRequested
PullRequestCreated

HumanFeedbackReceived
KnowledgeConflictDetected
```

---

## Task 3.3 — Local Event Bus

Create test/local implementation.

Support:

```text
publish
subscribe
handler registration
```

---

## Task 3.4 — Redis Event/Queue Adapter

If Redis is already part of deployment, implement:

```text
queue abstraction
worker consumption
retry
dead-letter behavior
```

Do not expose Redis-specific types outside adapter package.

---

## Task 3.5 — Idempotency

Add idempotency keys for external events.

Examples:

```text
provider webhook ID
repository commit SHA + event
document version ID
```

---

## Task 3.6 — Correlation/Causation Propagation

Ensure:

```text
webhook
 ↓
ingestion
 ↓
context
 ↓
execution
 ↓
verification
```

can be traced through one correlation chain.

---

## Phase 3 Completion Gate

A fake provider event should pass through the event system and update canonical state idempotently.

---

# 9. Phase 4 — Repository Registration and Source-Control Foundation

## Goal

Make Git repositories first-class inputs to the brain.

---

## Task 4.1 — SourceControlPort Contract

Required operations:

```text
register repository
clone/fetch
get default branch
get current revision
list changed files
read file at revision
create branch
create worktree
get diff
commit
push
```

PR operations may remain separate.

---

## Task 4.2 — Local Git Adapter

Implement using Git CLI or library.

Must support:

```text
local repo
bare/remote repo
revision-aware file read
changed-file detection
worktree creation
```

---

## Task 4.3 — Repository Scanner

On repository registration collect:

```text
tree structure
languages
manifest files
Dockerfiles
Compose files
CI configuration
documentation roots
test roots
```

---

## Task 4.4 — Repository Snapshot

Persist:

```text
repository revision
tree summary
detected languages
manifest list
documentation locations
```

---

## Task 4.5 — Incremental Revision Handler

On `RepositoryRevisionChanged`:

```text
determine old revision
determine new revision
get changed files
classify files
emit specialized ingestion jobs
```

Categories:

```text
source
test
documentation
manifest
configuration
deployment
schema
unknown
```

---

## Task 4.6 — GitLab Adapter

Implement only after LocalGitAdapter contract is stable.

Start with:

```text
repository metadata
webhooks
branches
commits
diff
push
```

PR/MR creation can wait until verification phase.

---

## Phase 4 Completion Gate

The brain can register a repository, identify its exact revision, detect changes, and create an isolated worktree.

---

# 10. Phase 5 — Document Ingestion and Canonical Documentation Model

## Goal

Ingest engineering documents without reducing them immediately to arbitrary vector chunks.

---

## Task 5.1 — SourceArtifact Model

Implement canonical input:

```text
source URI
provider
mime type
file name
revision/version
content hash
raw bytes reference
metadata
```

---

## Task 5.2 — Parser Registry

Create:

```text
DocumentParser
ParserRegistry
ParserSelectionPolicy
```

---

## Task 5.3 — Markdown Parser

Preserve:

```text
heading hierarchy
code blocks
links
tables
front matter
references
```

---

## Task 5.4 — HTML Parser

Preserve semantic hierarchy.

Avoid flattening navigation/header/footer noise into engineering content.

---

## Task 5.5 — Docling Adapter

Use Docling or equivalent only behind a parser adapter.

Target:

```text
PDF
DOCX
PPTX
complex external documents
```

Normalize output into:

```text
Document
DocumentVersion
DocumentNode
```

---

## Task 5.6 — ADR Parser

Detect standard ADR sections:

```text
context
decision
alternatives
consequences
status
```

Create `Decision` entities where confidence is sufficient.

---

## Task 5.7 — Requirement Extraction Hook

Do not perform full LLM requirement extraction yet.

Provide pipeline extension point:

```text
ParsedDocument
 ↓
EntityExtractor
 ↓
candidate requirements
```

---

## Task 5.8 — Link Extraction

Extract references such as:

```text
REQ-123
TASK-12
ADR-005
file paths
symbol references
URLs
```

Store unresolved references separately.

---

## Task 5.9 — Document Versioning

When a document changes:

```text
new version
compare content hash
preserve old version
update current version pointer
```

---

## Task 5.10 — Semantic Chunk Generation

Create chunks only after document structure exists.

Chunk metadata:

```text
document id
version id
heading path
node id
project
repository
commit
document type
```

---

## Task 5.11 — Ingestion Golden Tests

Fixtures:

```text
README
requirements document
ADR
PDF spec
nested Markdown docs
```

Expected outputs checked structurally.

---

## Phase 5 Completion Gate

A README, Markdown architecture document, and PDF specification can be transformed into structured canonical documents with preserved hierarchy and provenance.

---

# 11. Phase 6 — Software Topology Discovery

## Goal

Build project-level understanding even when Backstage or another software catalog does not exist.

---

## Task 6.1 — TopologyDiscoveryPort

Create pluggable discovery interface.

---

## Task 6.2 — Manifest Detectors

Implement detectors for the project's highest-priority ecosystems.

Start with:

```text
pyproject.toml
requirements.txt
package.json
Dockerfile
docker-compose.yml
```

Later:

```text
go.mod
Cargo.toml
Maven/Gradle
```

---

## Task 6.3 — Deployment Detectors

Parse:

```text
Docker Compose
Kubernetes
Helm
Terraform
```

where available.

---

## Task 6.4 — Component Classification

Derive candidates:

```text
service
application
library
worker
database
message broker
object store
external service
```

Every candidate stores provenance.

---

## Task 6.5 — API/Interface Discovery

Detect:

```text
OpenAPI
AsyncAPI
GraphQL
gRPC/protobuf
```

Create canonical `Interface` entities.

---

## Task 6.6 — Resource Discovery

Detect dependencies such as:

```text
PostgreSQL
Redis
Kafka
S3/MinIO
external HTTP services
```

---

## Task 6.7 — Topology Reconciliation

Support multiple claims:

```text
declared
discovered
inferred
```

Do not overwrite disagreement.

---

## Task 6.8 — DerivedSoftwareCatalog Service

Expose:

```text
list systems
list components
list interfaces
list resources
get dependencies
```

without requiring Backstage.

---

## Phase 6 Completion Gate

Given a repository with FastAPI + PostgreSQL + Redis + Docker Compose, the brain produces a reasonable canonical component/resource topology without human catalog metadata.

---

# 12. Phase 7 — Code Intelligence and Code Relation Graph

## Goal

Build revision-aware source-code intelligence capable of finding affected files and symbols.

Start with Python only unless the current codebase requires another language first.

---

## Task 7.1 — Code Parser Contract

Implement:

```text
LanguageParser
ParsedFile
Symbol
SymbolLocation
CodeRelation
```

---

## Task 7.2 — Python AST Parser

Extract:

```text
modules
classes
functions
methods
imports
decorators
parameters
return annotations
```

---

## Task 7.3 — Stable Symbol Identity

Define identity using:

```text
repository
revision
module
qualified name
symbol kind
```

Do not depend only on line number.

---

## Task 7.4 — Import Graph

Build:

```text
File IMPORTS File
Module IMPORTS Module
```

Resolve local imports where possible.

---

## Task 7.5 — Call Graph

Start with statically resolvable calls.

Relations:

```text
Function CALLS Function
Method CALLS Method
Function INSTANTIATES Class
```

Record confidence for unresolved/dynamic calls.

---

## Task 7.6 — Class Relationships

Extract:

```text
INHERITS
IMPLEMENTS
OVERRIDES
```

---

## Task 7.7 — Data Access Relations

Detect common patterns where possible:

```text
function reads model
function writes model
repository accesses table/model
```

Keep these conservative.

---

## Task 7.8 — Test Discovery

Identify:

```text
test files
test functions
fixtures
tested imports
likely tested symbols
```

---

## Task 7.9 — Code Summary Generation

For each:

```text
module
class
function
```

generate deterministic metadata first.

Optional LLM summary is stored as inferred semantic metadata.

---

## Task 7.10 — Incremental Code Graph Update

For changed files:

```text
remove/expire old revision facts
parse new file
upsert new symbols
recompute local relations
recompute affected reverse relations
```

---

## Task 7.11 — Impact Analysis Service

Input:

```text
target symbols
task concepts
repository revision
```

Output:

```text
primary symbols
direct dependents
reverse dependencies
related files
related tests
interfaces
configuration
risk score
```

---

## Task 7.12 — Impact Analysis Tests

Fixture repository should include:

```text
router
service
repository
model
tests
config
```

A known change should return the expected neighborhood.

---

## Phase 7 Completion Gate

For a selected function, the system can answer:

```text
where is it defined?
what does it call?
what calls it?
which files are related?
which tests are related?
```

for an exact repository revision.

---

# 13. Phase 8 — Neo4j Knowledge Graph

## Goal

Persist cross-domain relationships and enable graph traversal for context generation.

---

## Task 8.1 — Graph Schema

Define labels for:

```text
Project
Requirement
WorkItem
Decision
System
Component
Interface
Resource
Repository
File
Symbol
Test
Document
DocumentNode
Execution
Artifact
Evidence
Actor
```

---

## Task 8.2 — Relationship Schema

Implement a controlled vocabulary:

```text
PART_OF
DEPENDS_ON
IMPLEMENTS
MODIFIES
CONSTRAINS
CALLS
IMPORTS
READS
WRITES
PROVIDES
CONSUMES
TESTS
VALIDATES
VERIFIED_BY
REFERENCES
DERIVED_FROM
SUPERSEDES
ASSIGNED_TO
PRODUCED_BY
```

---

## Task 8.3 — Revision-Aware Graph Facts

Relationships related to code must carry:

```text
repository_id
commit_sha
origin
confidence
```

---

## Task 8.4 — Neo4j Adapter

Implement `KnowledgeGraphRepository`.

Functions:

```text
upsert nodes
upsert relations
query neighborhood
reverse traversal
relation filters
revision filters
```

---

## Task 8.5 — Graph Projection Services

Project canonical PostgreSQL entities into Neo4j.

Examples:

```text
Requirement → WorkItem
WorkItem → Component
Component → Repository
File → Symbol
Test → Symbol
Decision → Component
```

---

## Task 8.6 — Reconciliation Model

Support multiple evidence claims for one conceptual relation.

Example:

```text
payment-service DEPENDS_ON redis

evidence:
    Docker Compose
    source import
    runtime trace
```

---

## Task 8.7 — Graph Integrity Tests

Check:

- duplicate canonical nodes;
- orphan external IDs;
- invalid revision scope;
- unknown relation types.

---

## Phase 8 Completion Gate

A task can be traversed to requirement → component → repository → files → symbols → tests.

---

# 14. Phase 9 — Weaviate Semantic Index and Hybrid Retrieval

## Goal

Add semantic retrieval without making vector storage the source of truth.

---

## Task 9.1 — SemanticRecord Contract

Canonical fields:

```text
record_id
entity_id
entity_type
text
project_id
repository_id
revision
source
metadata
```

---

## Task 9.2 — Weaviate Adapter

Implement:

```text
index
delete
search
filter by project
filter by repository
filter by revision
filter by entity type
```

---

## Task 9.3 — Embedding Service Interface

Do not hard-code one embedding model.

Support:

```text
local embeddings
remote embeddings
future alternative
```

---

## Task 9.4 — Index Documents

Index:

```text
document nodes
requirements
decisions
```

---

## Task 9.5 — Index Code Summaries

Prefer symbol-level summaries instead of raw arbitrary source chunks where possible.

---

## Task 9.6 — Lexical Search Service

Implement lexical/BM25-like search or equivalent.

Hybrid retrieval should not rely on semantic search alone.

---

## Task 9.7 — Hybrid Candidate Retrieval

Combine:

```text
lexical
semantic
graph
code impact
```

into candidate records.

---

## Phase 9 Completion Gate

Given a task description, the system can retrieve semantically relevant documents while enforcing project/repository/revision filters.

---

# 15. Phase 10 — Context Engine and Context Capsules

## Goal

Build the central system that constructs precise, bounded task context.

---

## Task 10.1 — ContextRequest

Implement:

```text
work_item_id
executor capability
repository revision
context window
preferred token budget
context type
risk
```

---

## Task 10.2 — Context Candidate Model

Every candidate should include:

```text
entity
content
reason selected
retrieval source
relevance score
trust score
freshness
token estimate
```

---

## Task 10.3 — Retrieval Orchestrator

Gather candidates from:

```text
work item
requirements
knowledge graph
code graph
semantic search
lexical search
git history
previous executions
verification feedback
```

---

## Task 10.4 — Relevance Ranking

Initial deterministic ranking can use:

```text
direct graph distance
impact-analysis score
entity type
semantic score
lexical score
revision freshness
trust/provenance
```

Keep ranking pluggable.

---

## Task 10.5 — Token Estimation

Provide tokenizer-independent fallback plus model-specific tokenizers when known.

---

## Task 10.6 — Context Budget Allocator

Support allocation categories:

```text
task
requirements
architecture
source code
tests
history
instructions
```

---

## Task 10.7 — Context Capsule Models

Implement:

```text
PlanningContextCapsule
CodingContextCapsule
VerificationContextCapsule
```

---

## Task 10.8 — Context Explainability

Store why each item was included.

Example:

```text
services/auth.py

reason:
    contains primary impacted symbol

graph_distance:
    0

impact_score:
    0.98
```

---

## Task 10.9 — Just-in-Time Retrieval API

Expose tools:

```text
get_symbol_context
find_related_files
find_related_tests
get_requirement
get_decisions
search_project_knowledge
request_more_context
```

---

## Task 10.10 — Context Capsule Persistence

Store:

```text
capsule version
inputs
selected entities
scores
token counts
model budget
repository revision
```

This enables later evaluation.

---

## Task 10.11 — Context Regression Fixtures

Create known tasks and expected context.

Example:

```text
task:
    Change refresh token expiration.

must include:
    token service
    token config
    related tests
    ADR

must exclude:
    unrelated billing implementation
```

---

## Phase 10 Completion Gate

The system can build a compact context capsule for a task without invoking a coding agent.

This is the first major product milestone.

---

# 16. Phase 11 — Planning and Implementation-Status Intelligence

## Goal

Turn requirements and current project state into evidence-based engineering plans.

---

## Task 11.1 — Ambiguity Assessment

Input:

```text
requirements
documents
existing project state
```

Output:

```text
clear requirements
ambiguous requirements
missing information
assumptions
risk
```

---

## Task 11.2 — Requirement Extraction

Use structured output.

Every extracted requirement must retain source provenance.

---

## Task 11.3 — Planning Decomposition

Produce:

```text
feature
story
task
dependencies
acceptance criteria
```

Do not publish to OpenProject/Jira yet.

---

## Task 11.4 — Existing Implementation Analysis

For every planned task inspect:

```text
code graph
tests
git history
existing work items
```

Classify:

```text
NOT_IMPLEMENTED
PARTIALLY_IMPLEMENTED
IMPLEMENTED
IMPLEMENTED_BUT_UNVERIFIED
INCORRECT
UNKNOWN
```

---

## Task 11.5 — Plan Reconciliation

Do not duplicate work already completed.

Produce updated work plan.

---

## Task 11.6 — Plan Validation

Validate:

```text
every requirement covered
task dependencies valid
acceptance criteria present
no obvious duplicate tasks
technical order sensible
```

---

## Task 11.7 — Planning Evidence

Record what caused a task to be created.

Example:

```text
TASK-19 derives from REQ-4
```

---

## Phase 11 Completion Gate

Given a half-finished project and a requirements document, the system can produce an updated plan reflecting actual implementation status.

---

# 17. Phase 12 — Executor Abstraction and Pi Coding-Agent Integration

## Goal

Allow the brain to assign a task-specific context capsule to a replaceable coding executor.

---

## Task 12.1 — Executor Registry

Implement:

```text
ExecutorDescriptor
ExecutorCapabilities
ExecutorRegistry
```

---

## Task 12.2 — Model Capability Profiles

Represent:

```text
context window
preferred context budget
coding capability
reasoning capability
tool support
local/remote
cost class
```

---

## Task 12.3 — Workspace Manager

Implement:

```text
create isolated worktree
checkout base revision
create branch
cleanup workspace
```

---

## Task 12.4 — ExecutionRequest Builder

Build request from:

```text
WorkItem
ContextCapsule
Repository
Workspace
Permissions
Executor
```

---

## Task 12.5 — Fake Executor

Before Pi, implement deterministic fake executor for end-to-end tests.

---

## Task 12.6 — Pi Adapter

Integrate Pi behind `ExecutorPort`.

Prefer an integration mode that keeps the Python brain independent.

Possible early approach:

```text
Python brain
 ↓ JSONL/RPC
Pi process
```

Do not expose Pi session models to core domain.

---

## Task 12.7 — Pi Brain Tools

Provide task-scoped tools such as:

```text
brain_get_task
brain_get_symbol_context
brain_find_related_files
brain_find_related_tests
brain_get_requirement
brain_get_architecture_constraints
brain_request_more_context
```

---

## Task 12.8 — Tool Permission Enforcement

Executor receives only tools allowed by policy.

---

## Task 12.9 — Execution Result Collection

Collect:

```text
modified files
created files
deleted files
commands
tests
diff
observations
blockers
```

---

## Task 12.10 — Session vs Brain Memory Boundary

Ensure Pi session history is stored as execution/session metadata only.

Canonical project knowledge must not depend on Pi session files.

---

## Phase 12 Completion Gate

The brain can execute a WorkItem through Pi using a bounded context capsule and collect a structured result.

---

# 18. Phase 13 — Verification Engine and PR Readiness Gate

## Goal

Prevent code from reaching pull request solely because the coding agent says it is complete.

---

## Task 13.1 — VerificationPlan

Build verification requirements from:

```text
WorkItem
Acceptance criteria
Changed files
Impact analysis
Project configuration
```

---

## Task 13.2 — Deterministic Command Runner

Run project-configured checks:

```text
unit tests
integration tests
lint
format
type checks
build
```

Capture outputs as evidence.

---

## Task 13.3 — Changed-File Structural Analysis

Compare:

```text
expected impact set
actual changed files
```

Identify:

```text
missing expected change
unexpected high-risk change
```

---

## Task 13.4 — Architecture Rule Checker

Implement simple declarative constraints.

Example:

```text
services MUST_NOT_DEPEND_ON database adapters directly
```

---

## Task 13.5 — Test Relevance Checker

Determine whether relevant tests were:

```text
run
modified
added
missing
```

---

## Task 13.6 — Semantic Verification Agent

Build separate verification context.

Do not simply send coding-agent conversation.

Input:

```text
requirement
acceptance criteria
diff
relevant source
tests
architecture constraints
deterministic results
```

---

## Task 13.7 — Verification Verdict

Implement:

```text
PASS
PARTIAL
FAIL
BLOCKED
```

---

## Task 13.8 — Retry Feedback

Generate structured failure feedback for the next execution.

---

## Task 13.9 — PR Readiness Gate

Policy:

```text
PASS
  ↓
PR allowed

FAIL/PARTIAL/BLOCKED
  ↓
PR not automatically created
```

---

## Task 13.10 — PullRequestPort

Define canonical PR request/result contracts.

---

## Task 13.11 — GitLab Merge Request Adapter

Implement after gate is working.

---

## Phase 13 Completion Gate

An incorrect implementation that compiles but violates acceptance criteria must be rejected before PR creation.

---

# 19. Phase 14 — Work-Management Integration

## Goal

Treat AI agents as workers receiving tasks from interchangeable project-management systems.

---

## Task 14.1 — Work Management Mapping Specification

Map canonical fields to provider fields.

---

## Task 14.2 — OpenProject Adapter

Implement:

```text
fetch work item
list updates
create work item
update status
assign actor if supported
post execution/verification result
link PR
```

---

## Task 14.3 — OpenProject Webhook Normalization

Provider webhook:

```text
OpenProject event
 ↓
WorkItemChanged
```

---

## Task 14.4 — Integration Mapping Table

Persist:

```text
internal ID
provider
external ID
sync timestamps
sync state
```

---

## Task 14.5 — Sync Conflict Handling

Example:

```text
OpenProject says DONE
brain says verification FAILED
```

Do not overwrite either.

---

## Task 14.6 — Jira Adapter Skeleton

Implement enough to prove interchangeability.

Run same contract tests as OpenProject.

---

## Phase 14 Completion Gate

Switching `work_management.provider` should not change planning, context, execution, or verification services.

---

# 20. Phase 15 — Documentation and Catalog Integrations

## Goal

Allow human knowledge tools to enrich the brain without becoming mandatory.

---

## Task 15.1 — Git Markdown Documentation Adapter

Treat repository docs as a documentation provider.

---

## Task 15.2 — XWiki or Confluence Adapter

Choose one first.

Implement:

```text
fetch page
fetch page version
list changes
attachments
hierarchy
links
```

Normalize into canonical documents.

---

## Task 15.3 — Documentation Sync Events

Normalize changes to:

```text
DocumentChanged
```

---

## Task 15.4 — SoftwareCatalogPort Derived Implementation

Use brain-discovered topology as default.

---

## Task 15.5 — Backstage Adapter

Optional.

Read:

```text
Domain
System
Component
API
Resource
owner
dependencies
```

Map to canonical software model.

---

## Task 15.6 — Catalog Reconciliation

Compare:

```text
human-declared topology
brain-discovered topology
```

Create conflicts instead of silently overwriting.

---

## Phase 15 Completion Gate

The brain operates without XWiki/Confluence/Backstage, but can ingest them when configured.

---

# 21. Phase 16 — LangGraph Workflow Orchestration and Checkpointing

## Goal

Use LangGraph as an orchestration engine while keeping domain state independent.

---

## Task 16.1 — Define Workflow State

Workflow state should contain references, not copies of the entire project.

Example:

```text
workflow_id
project_id
work_item_id
current_execution_id
current_context_capsule_id
stage
retry_count
approval_state
```

---

## Task 16.2 — Build Main Engineering Graph

Suggested coarse graph:

```text
INTAKE
 ↓
UNDERSTAND
 ↓
BUILD_CONTEXT
 ↓
ROUTE_EXECUTOR
 ↓
EXECUTE
 ↓
VERIFY
 ↓
PASS?
 ├── NO → RETRY / HUMAN
 └── YES → PR
 ↓
UPDATE_BRAIN
 ↓
COMPLETE
```

---

## Task 16.3 — Planning Graph

Separate workflow for:

```text
ingest
extract requirements
assess ambiguity
inspect implementation
decompose
validate
publish plan
```

---

## Task 16.4 — PostgresSaver Checkpointer

Configure LangGraph PostgreSQL checkpointing.

Checkpoint store must be separate conceptually from domain execution records.

---

## Task 16.5 — Resume Tests

Simulate crash after:

```text
context build
execution start
verification start
```

Ensure workflow resumes safely.

---

## Task 16.6 — Retry Policies

Differentiate:

```text
transient tool failure
LLM failure
verification failure
invalid input
human-required decision
```

---

## Phase 16 Completion Gate

A workflow can crash and resume without losing domain execution history or duplicating irreversible operations.

---

# 22. Phase 17 — Human-in-the-Loop, Policies, and Permissions

## Goal

Make automation configurable and safe.

---

## Task 17.1 — Policy Model

Implement policies for:

```text
task risk
executor permissions
approval requirements
PR creation
merge
deployment
```

---

## Task 17.2 — ExecutionPermissions

Represent:

```text
repository read
repository write
shell
network
git commit
git push
PR create
merge
containers
secrets
deploy
```

---

## Task 17.3 — Approval Entity

Persist:

```text
approval type
requested by
approved/rejected by
reason
timestamp
related execution/work item
```

---

## Task 17.4 — Workflow Approval Nodes

Support:

```text
plan approval
architecture approval
security approval
PR approval
```

---

## Task 17.5 — Risk Classification

Initial rules can be deterministic.

High risk examples:

```text
database migration
authentication
authorization
cryptography
billing
production infrastructure
secrets
destructive operation
```

---

## Phase 17 Completion Gate

A configured high-risk task pauses for human approval while a low-risk task can continue automatically.

---

# 23. Phase 18 — Observability, Metrics, and Context-Quality Evaluation

## Goal

Measure whether the brain is actually improving software-engineering execution.

---

## Task 18.1 — Structured Logging

Every log event should carry available IDs:

```text
project_id
workflow_id
work_item_id
execution_id
correlation_id
```

---

## Task 18.2 — Execution Metrics

Capture:

```text
duration
model
tokens
tool calls
commands
retries
verification outcome
```

---

## Task 18.3 — Context Metrics

Capture:

```text
context token count
candidate count
selected entity count
retrieval source distribution
JIT retrieval requests
```

---

## Task 18.4 — Context Outcome Evaluation

Store signals:

```text
missing file discovered later
verifier found omitted dependency
agent requested additional context
irrelevant context rate
retry caused by context failure
```

---

## Task 18.5 — Impact Analysis Metrics

Measure:

```text
predicted affected files
actual changed files
false positives
false negatives discovered by verifier
```

---

## Task 18.6 — Dashboard/API

Expose project/system metrics through API or Grafana-compatible metrics.

---

## Phase 18 Completion Gate

For an execution, a developer can reconstruct:

```text
what context was selected
why it was selected
what model executed
what changed
why verification passed/failed
```

---

# 24. Phase 19 — Runtime Intelligence and Advanced Verification

## Goal

Enrich static understanding with observed behavior.

---

## Task 19.1 — Runtime Evidence Contract

Represent:

```text
trace
coverage
log event
service call
database access
message publish/consume
```

---

## Task 19.2 — Test Coverage Import

Map:

```text
test
 → executed file
 → executed symbol where feasible
```

---

## Task 19.3 — OpenTelemetry Import

Ingest safe development/test traces first.

---

## Task 19.4 — Runtime Dependency Graph

Add observed relations:

```text
SERVICE_CALLS
QUERY_ACCESSES
PUBLISHES_TO
CONSUMES_FROM
```

---

## Task 19.5 — Static vs Runtime Reconciliation

Example:

```text
static possible dependency
runtime observed dependency
```

Use runtime evidence to improve ranking but preserve both.

---

## Task 19.6 — Advanced Test Selection

Use:

```text
changed symbols
call graph
runtime coverage
test history
```

to select targeted verification tests.

---

## Phase 19 Completion Gate

The brain can explain both:

```text
what code may depend on a symbol
```

and:

```text
what tests/runtime paths actually exercised it
```

---

# 25. Phase 20 — Optimization, Model Routing, and Learning

## Goal

Improve cost, latency, context quality, and model selection after the core system is correct.

---

## Task 20.1 — Task Complexity Model

Features:

```text
affected files
affected components
graph depth
architecture risk
requirement ambiguity
previous failures
estimated context size
```

---

## Task 20.2 — Model Router

Policy examples:

```text
deterministic task
    → deterministic tool

small isolated code task
    → small local model

medium implementation
    → medium coding model

cross-component/high-risk task
    → large reasoning model
```

---

## Task 20.3 — Context Ranking Feedback

Use historical outcomes to adjust:

```text
retrieval weights
graph distance weights
entity priorities
token allocation
```

Start with explainable heuristics before learned policies.

---

## Task 20.4 — Test Selection Optimization

Use past verification data to reduce unnecessary test execution without compromising safety.

---

## Task 20.5 — Executor Quality Profiles

Track executor performance by task type.

Do not use one global "best model" score.

---

## Task 20.6 — Optional Learning Research

Explore:

```text
bandit routing
reward-based graph traversal weighting
context ranking learning
retrieval reinforcement
```

This must remain an optimization layer.

The base platform must still work without learned routing.

---

## Phase 20 Completion Gate

The system demonstrates improved:

```text
cost
latency
context efficiency
retry rate
```

without lowering verification quality.

---

# 26. Cross-Phase Testing Requirements

These tests should be built continuously.

---

## 26.1 Architecture Tests

Ensure:

```text
domain cannot import adapters
application cannot import provider SDKs
Neo4j types do not leak into domain
Pi types do not leak into executor contracts
OpenProject/Jira types do not leak into WorkItem
```

---

## 26.2 Adapter Contract Tests

Same tests run against:

```text
OpenProjectAdapter
JiraAdapter
```

and:

```text
XWikiAdapter
ConfluenceAdapter
```

where feature parity exists.

---

## 26.3 Golden Repository Tests

Maintain small fixture repositories representing:

```text
simple Python app
FastAPI service
multi-module service
service with PostgreSQL
service with tests
multi-service Compose project
```

---

## 26.4 Ingestion Regression Tests

Known input documents should generate stable structural representations.

---

## 26.5 Code Graph Regression Tests

For fixture repository, assert:

```text
symbols
imports
calls
tests
reverse callers
```

---

## 26.6 Context Regression Tests

These are mandatory before trusting small-model execution.

Each test includes:

```text
task
expected required context
known irrelevant context
token budget
```

---

## 26.7 End-to-End Execution Tests

Use fake executor first.

Flow:

```text
WorkItem
 ↓
Context
 ↓
Execution
 ↓
Verification
 ↓
PR readiness
```

---

## 26.8 Adversarial Verification Tests

Create broken implementations intentionally.

Examples:

```text
test passes but requirement incomplete
API contract accidentally changed
database schema changed without migration
security rule violated
agent modifies unrelated code
```

Verifier must reject them.

---

# 27. Definition of Done for the Full System

The Software Development Brain should eventually satisfy all of the following.

## Project Understanding

- Can register a new project.
- Can register one or multiple repositories.
- Can identify exact repository revision.
- Can ingest structured and unstructured documentation.
- Can derive software topology without Backstage.

## Code Understanding

- Can map repository → file → class/function.
- Can answer callers/callees.
- Can identify related tests.
- Can perform useful impact analysis.

## Knowledge

- Can connect requirements, tasks, code, tests, decisions, and components.
- Can preserve knowledge provenance.
- Can distinguish declared/discovered/observed/inferred facts.
- Can detect conflicts.

## Context

- Can construct task-specific context under a configured token budget.
- Can explain why each context item was selected.
- Can support just-in-time context retrieval.
- Can store context capsules for later analysis.

## Planning

- Can extract requirements.
- Can assess ambiguity.
- Can inspect partially implemented projects.
- Can generate tasks without duplicating already-completed work.

## Execution

- Can assign tasks to a human, Pi, another agent, or deterministic executor through one abstraction.
- Can isolate work in a Git worktree.
- Can collect structured execution results.

## Verification

- Can run deterministic checks.
- Can perform structural verification.
- Can perform independent semantic verification.
- Can block PR creation after failed verification.

## External Tools

- Can operate with OpenProject and later Jira through the same work-management contract.
- Can ingest documentation from Git and optionally XWiki/Confluence.
- Can consume Backstage when present but does not require it.

## Recovery

- Can checkpoint workflows.
- Can resume after process failure.
- Does not overwrite previous execution attempts.

## Observability

- Can trace requirement → task → context → execution → verification → PR.
- Can measure context quality and model effectiveness.

---

# 28. Recommended First Milestone

Do not try to build all phases before validating the core idea.

The recommended first usable milestone is:

```text
Phase 0
Phase 1
Phase 2
Phase 4
Phase 5
Phase 7
Phase 8
Phase 9
Phase 10
```

This produces:

```text
Git repository
      ↓
Document ingestion
      +
Code intelligence
      +
Knowledge graph
      +
Semantic retrieval
      ↓
Context Engine
      ↓
Precise Context Capsule
```

That milestone proves the most important hypothesis of the project:

> **Can the brain construct a better, smaller, more accurate context for a software-engineering task than a normal repository-search coding agent?**

Only after this works well should the project invest heavily in:

```text
planning automation
Pi coding-agent execution
verification loops
OpenProject/Jira integration
LangGraph orchestration
advanced model routing
```

The first milestone should therefore optimize for **context quality**, not autonomous coding.

A practical first end-to-end demonstration should be:

```text
1. Register a sample repository.

2. Ingest:
   - README
   - architecture docs
   - requirements
   - source code
   - tests

3. Build:
   - software topology
   - symbol graph
   - call/import graph
   - requirement/code relationships
   - semantic index

4. Submit a task:
   "Add account locking after five failed login attempts."

5. Generate a Context Capsule containing:
   - the exact requirement,
   - relevant architecture,
   - primary implementation symbols,
   - likely affected files,
   - related tests,
   - relevant configuration,
   - relevant previous decisions.

6. Verify that unrelated repository areas are excluded.

7. Measure:
   - token count,
   - relevant-file recall,
   - irrelevant-context ratio,
   - whether a small local model can understand the task from the capsule.
```

If this milestone succeeds, the architecture has validated the core idea of the Software Development Brain.

Everything after it is primarily about turning that intelligence into a reliable automation loop.
