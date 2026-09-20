# Development Brain

An AI-assisted engineering intelligence platform that connects to software-development tools, ingests project activity, builds a structured understanding of the project, and helps automate engineering workflows.

The system is designed to work both with **new projects**, where changes arrive continuously through webhooks, and with **well-established projects**, where historical project data must first be discovered, imported, normalized, and digested.

---

## 1. Purpose

Development Brain acts as a central intelligence layer between engineering tools such as:

- OpenProject
- Git repositories
- CI/CD systems
- Issue trackers
- Documentation systems
- Coding agents / LLM-based assistants

Its goal is to convert raw external-system data into a canonical internal representation that can be reasoned over by agents and automation workflows.

Typical use cases include:

- Understanding project structure and history
- Tracking requirements, tasks, bugs, and implementation changes
- Detecting meaningful project events
- Triggering engineering commands from events
- Performing change-impact analysis
- Recommending tests
- Supporting autonomous or semi-autonomous coding workflows
- Building project knowledge for an existing codebase
- Connecting tools such as Pi or other coding agents to project context

---

## 2. High-Level Architecture

```text
                    External Systems
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
   OpenProject          Git              CI/CD
        │                │                 │
        └──────────────┬─┴─────────────────┘
                       │
                Adapters / Transports
                       │
                       ▼
                Canonical Models
                       │
                       ▼
              Semantic Change Layer
                       │
                       ▼
                    Events
                       │
                       ▼
                Event Digestion
                       │
                       ▼
                   Commands
                       │
                       ▼
                 Command Queue
                       │
                       ▼
                    Workers
                       │
                       ▼
          Agents / Automation / Actions
```

The important design principle is:

> **External changes should first become domain events. Events are then interpreted to decide which commands, if any, should be executed.**

This keeps ingestion separate from decision-making and execution.

---

## 3. Core Concepts

### Adapter

An adapter connects Development Brain to an external system.

For example, the OpenProject adapter fetches work packages and converts them into the internal canonical representation.

```text
External API
    ↓
Transport
    ↓
Adapter
    ↓
Canonical Model
```

---

### Canonical Model

External systems use different data structures.

Development Brain normalizes them into common internal entities such as:

- Work items
- Projects
- Users
- Attachments
- Relationships
- Source-code changes
- Requirements
- Tests
- Defects

This allows downstream logic to remain independent of the original provider.

---

### Semantic Change

A semantic change represents the meaningful difference between the previous and current state of an entity.

Examples:

```text
TitleChanged
DescriptionChanged
PriorityChanged
StateChanged
AssigneeChanged
AttachmentAdded
ParentChanged
RelationAdded
```

Raw webhook payloads should not directly trigger engineering actions. They are first converted into semantic changes.

---

### Event

An event records something meaningful that has happened.

Example:

```text
WorkItemAssigned
RequirementUpdated
PullRequestMerged
BuildFailed
TestFailed
AttachmentAdded
```

Events describe facts.

They should not contain execution logic.

---

### Command

A command represents an action that the system wants to perform.

Examples:

```text
AnalyzeWorkItem
AnalyzeCodeChange
GenerateTests
ReviewImplementation
UpdateProjectKnowledge
InvestigateBuildFailure
```

Commands are normally created after an event has been interpreted.

```text
External Change
      ↓
Semantic Change
      ↓
Event
      ↓
Event Digestion
      ↓
Decision
      ↓
Command
      ↓
Queue
      ↓
Worker
```

---

## 4. OpenProject Integration

Development Brain supports two ingestion paths.

### 4.1 Pull-Based Ingestion

Used for:

- Initial project import
- Recovery
- Synchronization
- Historical backfill
- Periodic reconciliation

Typical flow:

```text
OpenProject API
      ↓
OpenProjectHTTPTransport
      ↓
OpenProjectAdapter
      ↓
Canonical WorkItem
      ↓
Persistence / Digestion
```

The adapter fetches work items from OpenProject and normalizes fields such as:

```text
subject      → title
description  → description
status       → state
assignee     → assignee
priority     → priority
```

---

### 4.2 Webhook-Based Ingestion

Used for live project updates.

Typical flow:

```text
OpenProject
    ↓
Webhook
    ↓
POST /api/v1/webhooks/openproject
    ↓
Payload Parser
    ↓
OpenProjectWorkItemSnapshot
    ↓
Diff Against Previous Snapshot
    ↓
Semantic Changes
    ↓
Events
```

A webhook may include changes to:

- Type
- Priority
- State
- Project
- Assignee
- Parent
- Attachments
- Relations

The webhook layer should remain lightweight and should avoid directly starting expensive agent workflows.

---

## 5. Event → Command Flow

A recommended processing model is:

```text
Webhook / Polling
       ↓
Canonical Update
       ↓
Semantic Change
       ↓
Domain Event
       ↓
Event Store / Event Queue
       ↓
Event Digester
       ↓
Rules / Agent Reasoning
       ↓
Command
       ↓
Command Queue
       ↓
Worker
```

### Why this separation matters

Without this separation:

```text
Webhook
   ↓
Command
```

the webhook layer becomes responsible for business decisions.

That causes problems when:

- multiple events need to be combined
- one event should trigger several commands
- an event should trigger no command
- commands depend on project context
- execution rules change
- events must be replayed
- historical data must be processed

With an event layer:

```text
Event = what happened
Command = what should be done
```

---

## 6. Command Queue

Commands are placed into a queue so that ingestion is independent from execution.

Conceptually:

```text
enqueue_command(...)
      ↓
CommandEnvelope
      ↓
CommandQueue
      ↓
Worker
      ↓
Command Handler
```

The queue implementation can differ between environments.

Example:

```text
Development / Tests
    → InMemoryCommandQueue

Production
    → RedisCommandQueue
```

This allows commands to be processed asynchronously by workers without blocking webhook requests.

---

## 7. Introducing Development Brain to an Existing Project

For a newly connected, well-established project, webhooks alone are not enough.

Webhooks only describe changes occurring **after installation**.

The system must first bootstrap the existing project.

### Bootstrap Flow

```text
Project Connected
      ↓
Discovery
      ↓
Historical Data Import
      ↓
Normalization
      ↓
Relationship Resolution
      ↓
Knowledge Digestion
      ↓
Checkpoint Created
      ↓
Live Webhook Processing Enabled
```

---

### Phase 1 — Discovery

Identify available project sources.

Examples:

```text
OpenProject
Git repositories
Documentation
CI/CD history
Test systems
Artifact stores
```

Store source metadata such as:

```text
provider
project ID
repository URL
default branch
last synchronization point
```

---

### Phase 2 — Historical Ingestion

Fetch existing data.

For OpenProject:

```text
Projects
Work packages
Statuses
Priorities
Users
Attachments
Relations
Parent / child relationships
```

For Git:

```text
Repositories
Branches
Commits
Tags
Pull / merge requests
Changed files
```

Historical ingestion should use pagination and checkpoints.

---

### Phase 3 — Normalization

Convert provider-specific records into canonical models.

```text
External Record
      ↓
Adapter
      ↓
Canonical Entity
```

The canonical entity should retain an external reference.

Example:

```text
provider: openproject
external_id: 1234
external_url: ...
```

This enables deduplication and later synchronization.

---

### Phase 4 — Relationship Resolution

After entities have been imported, resolve relationships such as:

```text
Requirement → Task
Task → Subtask
Task → Pull Request
Pull Request → Commit
Commit → File
Requirement → Test
Defect → Test
```

Some relationships cannot be resolved during the first import because the referenced entity may not yet exist.

A second pass is therefore recommended.

---

### Phase 5 — Knowledge Digestion

Imported data should be processed into useful project knowledge.

Examples:

- Project summaries
- Component ownership
- Requirement-to-code relationships
- Feature history
- Technical decisions
- Test coverage
- Known defects
- Common failure patterns
- Code dependencies

This stage may use:

- deterministic rules
- parsers
- embeddings
- graph construction
- LLM-based summarization
- coding agents

---

### Phase 6 — Create Synchronization Checkpoint

Once historical ingestion finishes, store a synchronization boundary.

Example:

```text
last_openproject_updated_at
last_git_commit_sha
last_ci_build_id
```

This prevents duplicate ingestion when live synchronization starts.

---

### Phase 7 — Enable Live Processing

After bootstrap:

```text
Webhook
   ↓
Semantic Change
   ↓
Event
   ↓
Event Digester
   ↓
Command
```

Periodic reconciliation can still run to catch missed events.

---

## 8. Recommended Bootstrap State Machine

```text
NOT_CONNECTED
      ↓
DISCOVERING
      ↓
IMPORTING
      ↓
NORMALIZING
      ↓
RESOLVING_RELATIONSHIPS
      ↓
DIGESTING
      ↓
READY
      ↓
LIVE_SYNC
```

Possible error states:

```text
IMPORT_FAILED
DIGEST_FAILED
SYNC_DEGRADED
```

The system should allow a failed phase to resume from its latest checkpoint.

---

## 9. Suggested Project Structure

```text
brain/
├── adapters/
│   ├── work_management/
│   │   └── openproject.py
│   ├── source_control/
│   └── queue/
│
├── api/
│   ├── routes/
│   │   └── webhooks.py
│   └── commands.py
│
├── bootstrap/
│   └── providers.py
│
├── domain/
│   ├── models/
│   ├── events/
│   ├── commands/
│   └── changes/
│
├── ingestion/
│   ├── discovery/
│   ├── historical/
│   ├── reconciliation/
│   └── checkpoints/
│
├── digestion/
│   ├── events/
│   ├── project/
│   └── code/
│
├── ports/
│   ├── work_management.py
│   ├── source_control.py
│   └── queue.py
│
├── workers/
│   ├── command_worker.py
│   └── ingestion_worker.py
│
└── agents/
    ├── coding/
    ├── analysis/
    └── testing/
```

The exact directory structure may evolve, but keeping **ports, adapters, domain logic, ingestion, digestion, and execution separated** is recommended.

---

## 10. Idempotency

Every ingestion path should be idempotent.

Processing the same webhook or historical record multiple times must not create duplicate entities or commands.

Useful identifiers include:

```text
provider + external_id
event_id
webhook_delivery_id
commit SHA
command_id
```

Example:

```text
(openproject, work_package, 1234)
```

should always refer to the same internal entity.

---

## 11. Reconciliation

Webhooks should not be considered the only source of truth.

A scheduled reconciliation process should periodically compare Development Brain with the external provider.

Example:

```text
list_changed_work_items(last_sync_time)
          ↓
Compare
          ↓
Import Missing Changes
          ↓
Update Checkpoint
```

This protects against:

- missed webhooks
- service downtime
- network failures
- provider retries
- deployment interruptions

---

## 12. Agent Integration

Coding agents should consume Development Brain context rather than independently querying every external system.

Recommended flow:

```text
Coding Agent
      ↓
Development Brain API / Tool Interface
      ↓
Project Context
      ↓
Relevant Work Items
      ↓
Code / Architecture Context
      ↓
Agent Reasoning
      ↓
Proposed Action
```

This makes the Brain the shared project-memory and context layer.

Agents such as Pi can therefore focus on:

- code analysis
- implementation
- debugging
- refactoring
- test generation

while Development Brain provides the project context required for those tasks.

---

## 13. Example End-to-End Scenario

A developer is assigned an OpenProject work package.

```text
1. OpenProject sends webhook
2. Webhook parser builds snapshot
3. Snapshot is compared with previous state
4. AssigneeChanged semantic change is detected
5. WorkItemAssigned event is created
6. Event digester reads the event
7. Digester determines that technical analysis is required
8. AnalyzeWorkItem command is created
9. Command is placed on the command queue
10. Worker consumes the command
11. Development Brain gathers relevant project context
12. Coding/analysis agent performs the task
13. Result is stored or published back to the project system
```

This design avoids embedding engineering decisions directly inside the webhook handler.

---

## 14. Existing-Project Example

Suppose Development Brain is introduced into a project that has already existed for three years.

At installation time there may already be:

```text
4,000 work packages
25,000 commits
1,200 pull requests
3,500 tests
900 defects
hundreds of documents
```

The system should not create artificial "new item" events for all historical records.

Instead:

```text
Historical Data
      ↓
Bootstrap Ingestion
      ↓
Knowledge Construction
```

Only after the bootstrap checkpoint should new changes enter the normal event pipeline.

```text
New Change
    ↓
Event
    ↓
Command
```

This distinction is essential.

---

## 15. Design Principles

1. **Adapters isolate external systems.**
2. **Canonical models isolate downstream logic from provider formats.**
3. **Events describe facts.**
4. **Commands describe actions.**
5. **Events should normally be interpreted before commands are created.**
6. **Webhook handlers should remain lightweight.**
7. **Historical ingestion and live ingestion are separate workflows.**
8. **Every ingestion operation should be idempotent.**
9. **Synchronization checkpoints must be persisted.**
10. **Periodic reconciliation should supplement webhooks.**
11. **Agents should consume centralized project context from Development Brain.**
12. **Long-running work should be executed through workers and queues.**

---

## 16. Future Capabilities

Potential extensions include:

- Requirement-to-code traceability
- Automatic change-impact analysis
- Test recommendation
- Test generation
- Architecture understanding
- Code ownership detection
- Defect root-cause analysis
- Project knowledge graphs
- Cross-repository reasoning
- Autonomous coding workflows
- Continuous documentation generation
- Release-risk analysis
- Engineering metrics
- Agent memory
- Human approval workflows

---

## 17. Development Status

The architecture currently includes concepts for:

- OpenProject pull integration
- OpenProject webhook ingestion
- Snapshot parsing
- Semantic change detection
- Command envelopes
- Command queues
- Redis-backed production queue
- In-memory development/test queue
- Worker-based command digestion

The next major architectural area is the **project bootstrap and historical-ingestion pipeline** for connecting Development Brain to already-established projects.

---

## 18. Summary

Development Brain is intended to become the engineering intelligence layer between development tools and AI agents.

The core processing model is:

```text
Data
  ↓
Canonical Knowledge
  ↓
Semantic Change
  ↓
Event
  ↓
Decision
  ↓
Command
  ↓
Execution
```

For an existing project:

```text
Discover
  ↓
Import History
  ↓
Normalize
  ↓
Resolve Relationships
  ↓
Digest
  ↓
Checkpoint
  ↓
Live Sync
```

This architecture allows the system to scale from simple webhook automation to a persistent AI-assisted engineering brain capable of understanding and acting across the complete software-development lifecycle.
