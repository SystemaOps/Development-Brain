# OpenProject Webhook Parsing — Concise Brain Guide

The Brain should extract only information useful for **workflow triggers**, **graph updates**, and **agent context**.

---

## 1. Webhook envelope

OpenProject webhooks have this shape:

```json
{
  "action": "work_package:updated",
  "work_package": { ... }
}
```

Observed actions:

```text
project:created
project:updated
work_package:created
work_package:updated
attachment:created
```

Always parse `action` first.

---

## 2. Work item structure

For work-package events:

```python
wp = payload["work_package"]
embedded = wp.get("_embedded") or {}
links = wp.get("_links") or {}
```

Important fields:

```text
work_package.id
work_package.subject
work_package.description.raw
work_package.createdAt
work_package.updatedAt

work_package._embedded.type
work_package._embedded.priority
work_package._embedded.status
work_package._embedded.project
work_package._embedded.assignee
work_package._embedded.attachments
work_package._embedded.relations

work_package._links.parent
work_package._links.activities
```

Recommended normalized work item:

```python
{
    "id": wp["id"],
    "summary": wp.get("subject"),
    "description": (wp.get("description") or {}).get("raw"),
    "type": (embedded.get("type") or {}).get("name"),
    "priority": (embedded.get("priority") or {}).get("name"),
    "state": (embedded.get("status") or {}).get("name"),
    "project_id": (embedded.get("project") or {}).get("id"),
    "assignee_id": (embedded.get("assignee") or {}).get("id"),
    "parent_id": id_from_href((links.get("parent") or {}).get("href")),
    "created_at": wp.get("createdAt"),
    "updated_at": wp.get("updatedAt"),
}
```

---

## 3. Summary and description

```python
summary = wp.get("subject")

description = (
    (wp.get("description") or {})
    .get("raw")
)
```

Use `description.raw`, not the rendered HTML, for LLM/context ingestion.

Possible semantic events:

```text
SUMMARY_CHANGED
DESCRIPTION_CHANGED
```

Use these to rebuild task context or invalidate an old plan.

---

## 4. Priority

Path:

```text
work_package._embedded.priority
```

Parse:

```python
priority = embedded.get("priority") or {}

priority_data = {
    "id": priority.get("id"),
    "name": priority.get("name"),
}
```

Example graph/property update:

```text
WorkItem.priority = "High"
```

Possible event:

```text
PRIORITY_CHANGED
```

Do not hard-code OpenProject numeric priority IDs.

---

## 5. State / status

Path:

```text
work_package._embedded.status
```

Parse:

```python
status = embedded.get("status") or {}

state = {
    "id": status.get("id"),
    "name": status.get("name"),
    "closed": status.get("isClosed"),
}
```

Possible event:

```text
STATE_CHANGED
```

Example workflow transitions:

```text
New → In Progress
    start/resume work

In Progress → Review
    trigger verification

Review → Closed
    finalize work item
```

---

## 6. Assignee

Assignee is optional.

Path:

```text
work_package._embedded.assignee
```

Parse safely:

```python
assignee = embedded.get("assignee")

assignee_id = assignee.get("id") if assignee else None
assignee_name = assignee.get("name") if assignee else None
```

Graph:

```text
(WorkItem)-[:ASSIGNED_TO]->(User)
```

Important workflow trigger:

```text
previous.assignee = null
current.assignee = Brain

→ WORK_ITEM_ASSIGNED_TO_BRAIN
```

Do not trigger coding merely because the webhook is `work_package:updated`.

---

## 7. Parent work item

Parent is referenced by:

```text
work_package._links.parent.href
```

Example:

```text
/api/v3/work_packages/20
```

Helper:

```python
def id_from_href(href: str | None) -> int | None:
    if not href:
        return None

    try:
        return int(href.rstrip("/").split("/")[-1])
    except ValueError:
        return None
```

Parse:

```python
parent_id = id_from_href(
    (links.get("parent") or {}).get("href")
)
```

Graph:

```text
(parent WorkItem)-[:PARENT_OF]->(child WorkItem)
```

Possible event:

```text
PARENT_CHANGED
```

This should update graph hierarchy and may require rebuilding inherited context.

---

## 8. Child work items

The supplied webhook samples do not contain a complete `children[]` list.

Build children from parent edges.

If:

```text
WorkItem 43.parent_id = 20
```

create:

```text
20 -[:PARENT_OF]-> 43
```

Children are then queried from the graph:

```cypher
MATCH (parent:WorkItem {external_id: "20"})
      -[:PARENT_OF]->(child:WorkItem)
RETURN child
```

Do not maintain a duplicate `children[]` list unless needed for caching.

---

## 9. Work-item relations

Path:

```text
work_package._embedded.relations._embedded.elements[]
```

Parse:

```python
relations = (
    ((embedded.get("relations") or {})
        .get("_embedded") or {})
        .get("elements")
    or []
)
```

Normalize each relation to:

```python
{
    "source_id": ...,
    "target_id": ...,
    "relation_type": ...,
}
```

Graph examples:

```text
WorkItem -[:RELATES_TO]-> WorkItem
WorkItem -[:BLOCKS]-> WorkItem
WorkItem -[:FOLLOWS]-> WorkItem
```

Use the actual relation type from OpenProject.

Possible event:

```text
RELATION_CHANGED
```

This can trigger dependency re-evaluation.

---

## 10. Attachments

### Embedded in work item

Path:

```text
work_package
└── _embedded
    └── attachments
        └── _embedded
            └── elements[]
```

Parse:

```python
attachments = (
    ((embedded.get("attachments") or {})
        .get("_embedded") or {})
        .get("elements")
    or []
)
```

Extract:

```python
[
    {
        "id": a.get("id"),
        "file_name": a.get("fileName"),
        "content_type": a.get("contentType"),
        "file_size": a.get("fileSize"),
        "download_url": (
            ((a.get("_links") or {})
                .get("downloadLocation") or {})
                .get("href")
        ),
    }
    for a in attachments
]
```

Graph:

```text
(WorkItem)-[:HAS_ATTACHMENT]->(Attachment)
```

### `attachment:created`

For attachment webhooks:

```python
attachment = payload["attachment"]
container = (
    (attachment.get("_embedded") or {})
    .get("container")
    or {}
)

work_item_id = container.get("id")
```

The supplied sample uses:

```text
container._type = WorkPackage
```

Possible workflow:

```text
ATTACHMENT_CREATED
    ↓
download
    ↓
parse document/image
    ↓
update agent context / graph
```

Use attachment ID for deduplication.

---

## 11. Comments

The supplied webhook bodies do **not** contain comments directly.

The work item exposes:

```text
work_package._links.activities.href
```

Parse:

```python
activities_url = (
    (links.get("activities") or {})
    .get("href")
)
```

Then:

```text
work-package webhook
        ↓
activities URL
        ↓
OpenProject API
        ↓
GET activities
        ↓
extract comments
```

Normalize comments as:

```python
{
    "id": "...",
    "work_item_id": 43,
    "author_id": "...",
    "text": "...",
    "created_at": "...",
}
```

Graph:

```text
(User)-[:AUTHORED]->(Comment)
(Comment)-[:COMMENT_ON]->(WorkItem)
```

Comments can create workflow events such as:

```text
COMMENT_ADDED
INSTRUCTION_ADDED
CLARIFICATION_ADDED
FEEDBACK_ADDED
APPROVAL_ADDED
REJECTION_ADDED
```

Classification can happen after the raw comment is stored.

---

## 12. Project relation

For work items:

```text
work_package._embedded.project
```

Extract:

```python
project = embedded.get("project") or {}

project_id = project.get("id")
project_name = project.get("name")
```

Graph:

```text
(Project)-[:CONTAINS]->(WorkItem)
```

For project/subproject webhooks:

```text
(Project)-[:PARENT_OF]->(Project)
```

---

## 13. Minimal graph model

```text
(Project)
    │
    ├── CONTAINS
    ▼
(WorkItem)
    │
    ├── PARENT_OF ─────> (WorkItem)
    ├── RELATES_TO ────> (WorkItem)
    ├── BLOCKS ────────> (WorkItem)
    ├── HAS_ATTACHMENT -> (Attachment)
    ├── HAS_COMMENT ───> (Comment)
    └── ASSIGNED_TO ───> (User)

(Project)-[:PARENT_OF]->(Project)
(User)-[:AUTHORED]->(Comment)
```

Useful WorkItem properties:

```text
external_id
summary
description
type
priority
state
created_at
updated_at
```

---

## 14. Convert updates into semantic events

`work_package:updated` is too generic.

Compare the new snapshot with the previous snapshot:

```python
previous = load_previous(work_item_id)
current = parse_work_item(payload)

if previous.summary != current.summary:
    emit("SUMMARY_CHANGED")

if previous.description != current.description:
    emit("DESCRIPTION_CHANGED")

if previous.assignee_id != current.assignee_id:
    emit("ASSIGNEE_CHANGED")

if previous.state != current.state:
    emit("STATE_CHANGED")

if previous.priority != current.priority:
    emit("PRIORITY_CHANGED")

if previous.parent_id != current.parent_id:
    emit("PARENT_CHANGED")
```

Then save the new snapshot.

---

## 15. Workflow vs graph update

| Change | Workflow | Graph update |
|---|---:|---:|
| Work item created | Yes | Yes |
| Summary changed | Maybe | Property update |
| Description changed | Yes | Property update |
| Priority changed | Maybe | Property update |
| State changed | Yes | Property update |
| Assignee changed | Yes | Yes |
| Assigned to Brain | **Yes** | Yes |
| Parent changed | Yes | **Yes** |
| Relation changed | Yes | **Yes** |
| Attachment created | Yes | **Yes** |
| Comment added | Yes | **Yes** |
| Project/subproject created | Maybe | **Yes** |

---

## 16. Minimal parser

```python
def parse_work_item(payload: dict) -> dict:
    wp = payload["work_package"]
    embedded = wp.get("_embedded") or {}
    links = wp.get("_links") or {}

    attachments = (
        ((embedded.get("attachments") or {})
            .get("_embedded") or {})
            .get("elements")
        or []
    )

    relations = (
        ((embedded.get("relations") or {})
            .get("_embedded") or {})
            .get("elements")
        or []
    )

    return {
        "id": wp["id"],
        "summary": wp.get("subject"),
        "description": (wp.get("description") or {}).get("raw"),
        "type": (embedded.get("type") or {}).get("name"),
        "priority": (embedded.get("priority") or {}).get("name"),
        "state": (embedded.get("status") or {}).get("name"),
        "project_id": (embedded.get("project") or {}).get("id"),
        "assignee_id": (embedded.get("assignee") or {}).get("id"),
        "parent_id": id_from_href((links.get("parent") or {}).get("href")),
        "attachments": [
            {
                "id": a.get("id"),
                "file_name": a.get("fileName"),
                "content_type": a.get("contentType"),
            }
            for a in attachments
        ],
        "relations": relations,
        "activities_url": (links.get("activities") or {}).get("href"),
        "created_at": wp.get("createdAt"),
        "updated_at": wp.get("updatedAt"),
    }
```

---

## 17. Core rule for the coding agent

```text
RAW OPENPROJECT WEBHOOK
          ↓
        PARSE
          ↓
 NORMALIZED SNAPSHOT
          ↓
  COMPARE OLD / NEW
          ↓
   SEMANTIC EVENTS
          ↓
     ┌────┴────┐
     ↓         ↓
GRAPH UPDATE  WORKFLOW
```

For every webhook ask:

```text
1. What entity changed?
2. What property changed?
3. What relationship changed?
4. Should the graph be updated?
5. Should a workflow be triggered?
6. Does the agent context need to be rebuilt?
```

Do not let OpenProject `_embedded` / `_links` structures leak into the Brain orchestrator.
