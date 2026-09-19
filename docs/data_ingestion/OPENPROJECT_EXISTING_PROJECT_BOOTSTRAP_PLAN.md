# OpenProject Existing Project Bootstrap Ingestion Plan

## Goal

Support onboarding of a **well-established OpenProject project** into Brain.

Initial onboarding must discover and ingest the project's current state before normal live synchronization begins.

```text
Initial onboarding
    = discover + ingest existing state

After onboarding
    = webhooks + periodic pull reconciliation
```

Bootstrap must **not trigger normal workflows for historical state**.

---

## Phase 1 — Bootstrap Command

Add a dedicated command:

```text
BOOTSTRAP_PROJECT
```

Input:

```text
provider = openproject
external_project_id
```

Flow:

```text
API / CLI / project connection
        ↓
BOOTSTRAP_PROJECT
        ↓
command queue
        ↓
worker
        ↓
OpenProjectProjectBootstrapService
```

Suggested lifecycle:

```text
CONNECTED
   ↓
DISCOVERING
   ↓
INGESTING
   ↓
BUILDING_GRAPH
   ↓
ESTABLISHING_BASELINE
   ↓
READY
   ↓
LIVE_SYNC
```

---

## Phase 2 — Discover Project Structure

Fetch the selected OpenProject project and extract:

```text
project id
identifier
name
description
parent project
ancestor projects
subprojects
```

Persist:

```text
Project
ExternalReference(openproject, project, external_id)
```

If hierarchy is supported:

```text
Project.parent_id
```

Graph:

```text
(Project)-[:PARENT_OF]->(Project)
```

---

## Phase 3 — Fetch All Existing Work Items

During bootstrap, do **not** use only:

```text
updated_since(...)
```

Fetch all work packages for the selected project using pagination.

Extract:

```text
id
summary
description
type
priority
state/status
project
author
assignee
parent
relations
attachments
created_at
updated_at
```

Normalize into:

```python
OpenProjectWorkItemSnapshot
```

Persist:

```text
WorkItem
ExternalReference(openproject, work_item, external_id)
IntegrationMapping
```

Use:

```python
mode = "BOOTSTRAP"
```

Historical state must not trigger workflow events.

Example:

```text
Existing task already assigned to Brain
        ↓
store assignee
        ↓
DO NOT emit WorkItemAssigned
        ↓
DO NOT enqueue RUN_WORK_ITEM
```

---

## Phase 4 — Two-Pass Relationship Resolution

Resources may arrive in any order.

### Pass 1 — Create entities

Create/update:

```text
Projects
WorkItems
Users/references
Attachment metadata
```

### Pass 2 — Resolve relationships

Example:

```text
OpenProject WorkPackage 43
parent = WorkPackage 21
```

Resolve:

```text
(openproject, work_item, 21)
        ↓
Brain WorkItem UUID
```

Then persist:

```text
WorkItem43.parent_id = WorkItem21.id
```

Resolve relations such as:

```text
parent-child
blocks
relates-to
precedes
follows
```

Graph:

```text
(WorkItem)-[:PARENT_OF]->(WorkItem)
(WorkItem)-[:BLOCKS]->(WorkItem)
(WorkItem)-[:RELATES_TO]->(WorkItem)
```

---

## Phase 5 — Comments / Activities

For each relevant WorkItem, fetch:

```text
/work_packages/{id}/activities
```

Extract:

```text
comment id
work item id
author id
text
created_at
```

Store historical comments as project context.

Graph:

```text
(User)-[:AUTHORED]->(Comment)
(Comment)-[:COMMENT_ON]->(WorkItem)
```

Important distinction:

```text
BOOTSTRAP COMMENT
    → context only

NEW LIVE COMMENT
    → HumanFeedbackReceived
    → may resume workflow
```

Do not emit `HumanFeedbackReceived` for historical comments.

---

## Phase 6 — Attachments

Ingest metadata:

```text
attachment id
file name
content type
file size
container work item
download reference
```

Persist:

```text
Attachment
ExternalReference(openproject, attachment, external_id)
```

Graph:

```text
(WorkItem)-[:HAS_ATTACHMENT]->(Attachment)
```

Apply an ingestion policy:

```text
PDF / Markdown / text
    → download
    → parse
    → semantic index

images / diagrams
    → artifact/context

large binary/archive
    → metadata only unless required
```

---

## Phase 7 — Build Canonical Graph

Project the imported state into the graph.

Minimum useful graph:

```text
(Project)-[:PARENT_OF]->(Project)

(WorkItem)-[:PART_OF]->(Project)

(WorkItem)-[:PARENT_OF]->(WorkItem)

(WorkItem)-[:BLOCKS]->(WorkItem)

(WorkItem)-[:RELATES_TO]->(WorkItem)

(WorkItem)-[:ASSIGNED_TO]->(User)

(WorkItem)-[:HAS_COMMENT]->(Comment)

(WorkItem)-[:HAS_ATTACHMENT]->(Attachment)
```

Use provider identity:

```text
(provider, entity_type, external_id)
```

Never use titles or names as identifiers.

---

## Phase 8 — Establish Durable Baseline Snapshots

Persist the current normalized state of every WorkItem.

Store:

```text
external_id
normalized snapshot
updated_at
ingested_at
```

This becomes the baseline for future diffs.

Without durable snapshots, a restart may make existing state appear new.

Example risk:

```text
existing assignee = Brain
restart
snapshot lost
next webhook arrives
        ↓
assignment may look new
        ↓
duplicate RUN_WORK_ITEM
```

---

## Phase 9 — Establish Sync Watermark

Store:

```text
bootstrap_started_at
bootstrap_completed_at

provider = openproject
sync_key = work_items:<project-id>
last_updated_at
last_external_id
```

After bootstrap, begin incremental sync with a small overlap.

Example:

```text
bootstrap completed = 13:00:00

first pull starts from = 12:59:55
```

This protects against changes that occurred while bootstrap was running.

---

## Phase 10 — Enable Live Synchronization

Only after project state becomes:

```text
READY
```

enable:

```text
OpenProject Webhooks
        +
Periodic Pull Reconciliation
```

Live flow:

```text
new provider snapshot
        ↓
load previous durable snapshot
        ↓
diff
        ↓
SemanticChange[]
        ↓
graph update
        +
workflow trigger
```

Useful live events:

```text
ASSIGNEE_CHANGED
STATE_CHANGED
PRIORITY_CHANGED
DESCRIPTION_CHANGED
PARENT_CHANGED
RELATION_CHANGED
ATTACHMENT_CREATED
COMMENT_ADDED
```

---

## Phase 11 — Unified Ingestion Service

Webhook, bootstrap, and pull should share the same canonical ingestion path.

Recommended API:

```python
async def ingest_work_item_snapshot(
    snapshot: OpenProjectWorkItemSnapshot,
    *,
    mode: Literal["BOOTSTRAP", "LIVE"],
    source: Literal["bootstrap", "webhook", "pull"],
):
    ...
```

Common responsibilities:

```text
identity resolution
WorkItem persistence
parent resolution
relation resolution
attachment reconciliation
snapshot persistence
graph update
```

Mode behavior:

```text
BOOTSTRAP
    persist state
    build graph
    create baseline
    NO workflow triggers

LIVE
    compare old/new
    emit semantic changes
    trigger workflows
```

---

## Phase 12 — Bootstrap Service

Suggested module:

```text
brain/application/openproject_bootstrap.py
```

Service:

```text
OpenProjectProjectBootstrapService
```

Responsibilities:

```text
discover project hierarchy
fetch all work items
paginate
normalize
persist entities
resolve relationships
ingest comments
ingest attachments
build graph
save snapshots
save watermark
mark project READY
```

Reuse the same OpenProject parsing/normalization used by webhooks.

---

## Phase 13 — Idempotency

Bootstrap must be safe to run multiple times.

Identity examples:

```text
(openproject, project, 8)
(openproject, work_item, 43)
(openproject, attachment, 3)
```

Behavior:

```text
existing entity
    → update/reconcile

missing entity
    → create
```

Never deduplicate by:

```text
project name
work item title
attachment filename
```

---

## Phase 14 — Failure and Resume

Persist bootstrap progress:

```text
project_id
provider
status
started_at
completed_at
current_stage
last_page
items_processed
last_error
```

Suggested stages:

```text
DISCOVER_PROJECTS
FETCH_WORK_ITEMS
RESOLVE_RELATIONS
INGEST_COMMENTS
INGEST_ATTACHMENTS
BUILD_GRAPH
ESTABLISH_BASELINE
COMPLETE
```

On failure, either:

```text
resume from last checkpoint
```

or:

```text
restart idempotently
```

---

## Phase 15 — Tests

### Existing project import

Given:

```text
1 project
2 subprojects
100 existing work items
```

Verify:

```text
all entities imported
no duplicates
project hierarchy persisted
```

### Work item hierarchy

Given:

```text
WP 21 parent of WP 43
```

Verify:

```text
WorkItem43.parent_id == WorkItem21.id
graph contains PARENT_OF
```

### Historical Brain assignment

Existing task already assigned to Brain:

Verify:

```text
assignee persisted
NO WorkItemAssigned event
NO RUN_WORK_ITEM command
```

### Historical comments

Verify:

```text
comments stored/indexed
NO HumanFeedbackReceived emitted
```

A new comment after bootstrap should emit:

```text
HumanFeedbackReceived
```

### Attachments

Verify:

```text
metadata imported
attachment linked to WorkItem
re-running bootstrap does not duplicate it
```

### Changes during bootstrap

Simulate:

```text
bootstrap starts
provider item changes
bootstrap completes
overlap pull runs
```

Verify:

```text
change is not lost
semantic processing happens once
```

### Restart

Verify:

```text
snapshots survive
watermark survives
bootstrap state survives
```

---

## Recommended Implementation Order

```text
1. External-reference reverse lookup
        ↓
2. Durable WorkItem snapshots
        ↓
3. Project + WorkItem hierarchy persistence
        ↓
4. BOOTSTRAP_PROJECT command
        ↓
5. Full project/work-item pagination
        ↓
6. Two-pass relationship resolution
        ↓
7. Historical comments
        ↓
8. Attachments
        ↓
9. Graph projection
        ↓
10. Establish baseline + watermark
        ↓
11. Enable webhook + pull live sync
        ↓
12. Retry/resume + tests
```

---

## Final Architecture

```text
                EXISTING OPENPROJECT PROJECT
                           │
                           ▼
                   BOOTSTRAP_PROJECT
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
          Projects      WorkItems      Activities
             │             │             │
             │             ├──────┐      │
             ▼             ▼      ▼      ▼
       Project tree     Relations Attachments Comments
             │             │      │      │
             └─────────────┴──────┴──────┘
                           │
                           ▼
                Canonical PostgreSQL State
                           │
                           ▼
                    Knowledge Graph
                           │
                           ▼
                  Durable Snapshots
                           │
                           ▼
                     Sync Watermark
                           │
                           ▼
                         READY
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
          Webhooks                 Pull Reconcile
             │                           │
             └─────────────┬─────────────┘
                           ▼
                       LIVE DIFF
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
        Graph Update                 Workflow
```

## Core Rule

```text
Bootstrap teaches Brain what already exists.

Webhooks and pull synchronization tell Brain what changed afterward.
```
