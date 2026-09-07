# OpenProject Webhook Data Structure and Parsing Guide

> Coding-agent implementation reference for the Brain / OpenProject adapter.
>
> This document is based on the captured OpenProject webhook payloads supplied during development. It describes the observed payload shapes, how to extract data safely, and how to normalize provider-specific webhook data before the rest of the Brain consumes it.

---

## 1. Purpose

OpenProject sends webhook notifications when resources change. The webhook payload is rich and contains:

- the event action;
- the primary resource affected by the event;
- embedded related resources;
- links to related resources and available API operations.

The Brain should **not pass the complete OpenProject payload into planning, coding, verification, or domain services**.

Instead:

```text
OpenProject HTTP webhook
        ↓
OpenProject webhook adapter
        ↓
verify transport/signature
        ↓
parse provider payload
        ↓
extract provider entities/references
        ↓
normalize into canonical Brain event
        ↓
persist + dispatch
```

OpenProject-specific structures such as `_embedded`, `_links`, `/api/v3/...` paths, type IDs, and status IDs must remain inside the OpenProject integration layer.

---

# 2. Webhook Events Observed

The supplied webhook samples contain the following actions:

| OpenProject action | Top-level resource key | Meaning |
|---|---|---|
| `project:created` | `project` | A project or subproject was created |
| `project:updated` | `project` | A project or subproject was updated |
| `work_package:created` | `work_package` | A work package was created |
| `work_package:updated` | `work_package` | A work package was updated |
| `attachment:created` | `attachment` | An attachment was created, in the sample on a work package |

The generic top-level shape is therefore:

```json
{
  "action": "<resource>:<operation>",
  "<resource>": {
    "...": "resource snapshot"
  }
}
```

Examples:

```json
{
  "action": "project:created",
  "project": {}
}
```

```json
{
  "action": "work_package:updated",
  "work_package": {}
}
```

```json
{
  "action": "attachment:created",
  "attachment": {}
}
```

Do **not** assume that every action uses `work_package` as the resource key.

---

# 3. Transport Data vs Webhook Body

Keep the HTTP transport information separate from the JSON body.

Observed request transport data includes:

```text
Content-Type: application/json
X-OP-Signature: sha1=<hex-value>
User-Agent: Faraday ...
```

The raw HTTP body is JSON bytes:

```python
raw = await request.body()
```

After successful signature verification:

```python
payload = json.loads(raw)
```

A log entry such as:

```python
body={'action': 'project:created', ...}
```

is a **Python representation of an already-parsed dictionary**.

It is not the literal wire representation of JSON.

For example, logs may show:

```python
True
False
None
```

where actual JSON uses:

```json
true
false
null
```

The parser must always operate on the actual incoming JSON body, not by parsing a copied log string.

---

# 4. Signature Verification

Signature verification must happen against the **exact raw request bytes**.

Recommended flow:

```python
raw_body = await request.body()
signature = request.headers.get("x-op-signature")

verify_signature(
    raw_body=raw_body,
    signature=signature,
)

payload = json.loads(raw_body)
```

Do not:

1. parse JSON;
2. serialize it again;
3. verify the signature against the reserialized JSON.

Whitespace, escaping, key ordering, and encoding can change during serialization.

The supplied logs show an `x-op-signature` header while one error message reports an empty application-side signature value. The webhook handler should therefore explicitly test header extraction.

Example diagnostic:

```python
signature = request.headers.get("x-op-signature")

if not signature:
    logger.warning(
        "OpenProject signature missing",
        extra={
            "available_headers": list(request.headers.keys()),
        },
    )
```

Do not log secrets or full authentication credentials.

---

# 5. OpenProject Payload Design

The payload follows three important structural concepts:

```text
resource fields
_embedded
_links
```

Example:

```json
{
  "_type": "WorkPackage",
  "id": 43,
  "subject": "test",

  "_embedded": {
    "type": {},
    "priority": {},
    "project": {},
    "status": {},
    "author": {}
  },

  "_links": {
    "self": {},
    "project": {},
    "parent": {},
    "attachments": {}
  }
}
```

Their roles are different.

## 5.1 Direct fields

Direct fields describe the primary resource itself.

Examples:

```text
id
identifier
name
subject
description
createdAt
updatedAt
active
public
startDate
dueDate
lockVersion
```

Use these as the primary source for attributes of the current resource.

---

## 5.2 `_embedded`

`_embedded` contains related resources that OpenProject included directly in the webhook snapshot.

Examples from the supplied samples:

```text
project._embedded.parent
work_package._embedded.project
work_package._embedded.type
work_package._embedded.priority
work_package._embedded.status
work_package._embedded.author
work_package._embedded.assignee
work_package._embedded.attachments
work_package._embedded.relations
attachment._embedded.author
attachment._embedded.container
```

Embedded resources are convenient, but their presence is **conditional**.

Never write code such as:

```python
assignee_id = payload["work_package"]["_embedded"]["assignee"]["id"]
```

because `_embedded.assignee` is absent when there is no assignee.

Prefer:

```python
embedded = work_package.get("_embedded") or {}
assignee = embedded.get("assignee")
assignee_id = assignee.get("id") if assignee else None
```

---

## 5.3 `_links`

`_links` contains references and API affordances.

A link usually looks like:

```json
{
  "href": "/api/v3/projects/8",
  "title": "Infrastructure"
}
```

Some links also contain:

```text
method
type
payload
templated
```

Examples:

```json
{
  "href": "/api/v3/work_packages/43",
  "method": "patch"
}
```

Use `_links` primarily for:

- stable provider references;
- relationships when the related object is not embedded;
- follow-up API calls;
- resource navigation.

Do not persist every action link into the Brain domain model.

Most links such as:

```text
update
delete
pdf
copy
move
previewMarkup
showCosts
github
gitlab
meetings
```

are provider API affordances, not domain knowledge.

---

# 6. General Extraction Strategy

Use this precedence:

```text
1. direct resource fields
2. embedded related resource
3. relationship link
4. optional OpenProject API fetch if richer/current state is required
```

Example for a work package project:

```text
work_package._embedded.project.id
        ↓ preferred

work_package._links.project.href
        ↓ fallback reference

GET /api/v3/projects/{id}
        ↓ optional enrichment
```

The webhook processor should avoid unnecessary API requests when the webhook already contains the required data.

---

# 7. Common Rich-Text Structure

Project descriptions, work-package descriptions, attachment descriptions, and status explanations use a structure like:

```json
{
  "format": "markdown",
  "raw": "Description",
  "html": "<p class=\"op-uc-p\">Description</p>"
}
```

For Brain ingestion:

```text
raw = canonical source text
html = presentation/rendered representation
format = source format metadata
```

Recommended canonical extraction:

```python
def extract_text(value: dict | None) -> str:
    if not value:
        return ""
    return value.get("raw") or ""
```

For LLM/context/document ingestion, prefer `raw`.

Do not use the HTML version as the primary textual source unless HTML-specific information is required.

---

# 8. Project Structure

Observed project payload:

```text
Project
├── _type
├── id
├── identifier
├── name
├── active
├── public
├── description
├── createdAt
├── updatedAt
├── statusExplanation
├── _embedded? 
│   └── parent?
└── _links
    ├── self
    ├── workPackages
    ├── ancestors
    ├── parent
    └── ...
```

## 8.1 Important project fields

| Canonical meaning | OpenProject path | Required for extraction |
|---|---|---|
| Provider project ID | `project.id` | Yes |
| Identifier/slug | `project.identifier` | Yes |
| Name | `project.name` | Yes |
| Active | `project.active` | Recommended |
| Public | `project.public` | Recommended |
| Description | `project.description.raw` | Optional |
| Created timestamp | `project.createdAt` | Recommended |
| Updated timestamp | `project.updatedAt` | Recommended |
| Immediate parent | `project._embedded.parent.id` | Optional |
| Parent reference | `project._links.parent.href` | Optional |
| Ancestor chain | `project._links.ancestors[]` | Optional |

---

# 9. Root Project vs Subproject

A root project sample contains:

```json
{
  "_links": {
    "ancestors": [],
    "parent": {
      "href": null
    }
  }
}
```

and does not require:

```text
_embedded.parent
```

A subproject sample contains:

```text
project._embedded.parent
```

and:

```text
project._links.ancestors
project._links.parent
```

Example hierarchy from the supplied samples:

```text
Odoo deployment        project id=3
└── Project 2          project id=4
    └── Infrastructure project id=8
```

For project `Infrastructure`, `_links.ancestors` contains:

```text
Odoo deployment
Project 2
```

and `_links.parent` points directly to:

```text
Project 2
```

---

# 10. Parsing Project Hierarchy

Prefer IDs for identity.

Names/titles are display values only.

Helper:

```python
import re

RESOURCE_ID_RE = re.compile(r"/api/v3/[^/]+/(\d+)$")


def id_from_href(href: str | None) -> int | None:
    if not href:
        return None

    match = RESOURCE_ID_RE.search(href)
    return int(match.group(1)) if match else None
```

Parent extraction:

```python
def extract_project_parent(project: dict) -> dict | None:
    embedded = project.get("_embedded") or {}

    if embedded.get("parent"):
        parent = embedded["parent"]
        return {
            "id": parent.get("id"),
            "identifier": parent.get("identifier"),
            "name": parent.get("name"),
        }

    parent_link = (project.get("_links") or {}).get("parent") or {}
    parent_id = id_from_href(parent_link.get("href"))

    if parent_id is None:
        return None

    return {
        "id": parent_id,
        "identifier": None,
        "name": parent_link.get("title"),
    }
```

Ancestor extraction:

```python
def extract_project_ancestors(project: dict) -> list[dict]:
    links = project.get("_links") or {}
    ancestors = links.get("ancestors") or []

    result = []

    for position, ancestor in enumerate(ancestors):
        result.append(
            {
                "id": id_from_href(ancestor.get("href")),
                "name": ancestor.get("title"),
                "position": position,
            }
        )

    return result
```

Do not infer project identity from ancestor title.

---

# 11. Canonical Project Extraction

Recommended provider-neutral structure:

```python
class ExternalRef(BaseModel):
    provider: str
    entity_type: str
    external_id: str


class ProjectSnapshot(BaseModel):
    external_ref: ExternalRef
    identifier: str
    name: str

    description: str = ""
    active: bool | None = None
    public: bool | None = None

    parent_external_id: str | None = None
    ancestor_external_ids: list[str] = []

    created_at: datetime | None = None
    updated_at: datetime | None = None
```

Example output:

```json
{
  "external_ref": {
    "provider": "openproject",
    "entity_type": "project",
    "external_id": "8"
  },
  "identifier": "infrastructure",
  "name": "Infrastructure",
  "description": "",
  "active": true,
  "public": false,
  "parent_external_id": "4",
  "ancestor_external_ids": ["3", "4"]
}
```

---

# 12. Work Package Structure

A work package is the generic OpenProject work-management entity.

A work package may represent a:

```text
Task
Story
Epic
Bug
Feature
Milestone
custom configured type
```

Do not equate:

```text
work_package == task
```

Instead:

```text
work package
    ↓
type
    ↓
Task / Story / Epic / ...
```

Observed work-package structure:

```text
WorkPackage
├── _type
├── id
├── lockVersion
├── subject
├── description
├── scheduleManually
├── startDate
├── dueDate
├── estimatedTime
├── spentTime
├── percentageDone
├── createdAt
├── updatedAt
├── costs...
├── _embedded
│   ├── attachments
│   ├── relations
│   ├── type
│   ├── priority
│   ├── project
│   ├── status
│   ├── author
│   ├── assignee? 
│   └── costsByType
└── _links
    ├── self
    ├── project
    ├── type
    ├── priority
    ├── status
    ├── author
    ├── assignee
    ├── responsible
    ├── parent
    ├── attachments
    ├── relations
    └── ...
```

---

# 13. Important Work-Package Fields

| Canonical meaning | Preferred OpenProject path |
|---|---|
| Work item ID | `work_package.id` |
| Version for optimistic locking | `work_package.lockVersion` |
| Title | `work_package.subject` |
| Description | `work_package.description.raw` |
| Start date | `work_package.startDate` |
| Due date | `work_package.dueDate` |
| Estimated time | `work_package.estimatedTime` |
| Time spent | `work_package.spentTime` |
| Completion percentage | `work_package.percentageDone` |
| Created | `work_package.createdAt` |
| Updated | `work_package.updatedAt` |
| Type ID | `work_package._embedded.type.id` |
| Type name | `work_package._embedded.type.name` |
| Priority ID | `work_package._embedded.priority.id` |
| Priority name | `work_package._embedded.priority.name` |
| Status ID | `work_package._embedded.status.id` |
| Status name | `work_package._embedded.status.name` |
| Project ID | `work_package._embedded.project.id` |
| Project identifier | `work_package._embedded.project.identifier` |
| Project name | `work_package._embedded.project.name` |
| Author ID | `work_package._embedded.author.id` |
| Assignee ID | `work_package._embedded.assignee.id` if present |
| Parent work-package ID | parse `work_package._links.parent.href` if present |
| Attachments | `work_package._embedded.attachments._embedded.elements[]` |
| Relations | `work_package._embedded.relations._embedded.elements[]` |

---

# 14. Do Not Hard-Code Type, Status, or Priority IDs

The samples contain values such as:

```text
Type:
  id = 1
  name = Task

Status:
  id = 1
  name = New

Priority:
  id = 8
  name = Normal

Priority:
  id = 9
  name = High
```

These IDs belong to the particular OpenProject configuration.

Do not write:

```python
if type_id == 1:
    canonical_type = "TASK"
```

Prefer configured mapping:

```yaml
openproject:
  type_mapping:
    Task: TASK
    Story: STORY
    Epic: EPIC
    Bug: BUG

  status_mapping:
    New: NEW
    In progress: IN_PROGRESS
    Closed: DONE
```

Names are useful for resolving configured mappings, but the integration should persist both ID and name.

---

# 15. Assignee Is Optional and Event-Dependent

One `work_package:updated` sample includes:

```text
work_package._embedded.assignee
```

with a Brain service account.

Other work-package payloads contain no embedded assignee and only:

```json
"_links": {
  "assignee": {
    "href": null
  }
}
```

Therefore:

```python
def extract_assignee(work_package: dict) -> dict | None:
    embedded = work_package.get("_embedded") or {}
    assignee = embedded.get("assignee")

    if assignee:
        return {
            "id": assignee.get("id"),
            "name": assignee.get("name"),
            "login": assignee.get("login"),
            "email": assignee.get("email"),
        }

    link = (work_package.get("_links") or {}).get("assignee") or {}
    assignee_id = id_from_href(link.get("href"))

    if assignee_id is None:
        return None

    return {
        "id": assignee_id,
        "name": link.get("title"),
        "login": None,
        "email": None,
    }
```

The Brain should detect assignment transitions by comparing the new normalized snapshot with the previously persisted snapshot.

Example:

```text
previous assignee = null
new assignee = OpenProject user 6
            ↓
canonical event:
WorkItemAssigned
```

Do not treat every `work_package:updated` event containing an assignee as a new assignment.

---

# 16. Work-Package Parent

In the supplied work-package samples:

```json
"parent": {
  "href": null,
  "title": null
}
```

When OpenProject sends a parent relationship, treat the provider reference as authoritative.

Recommended extraction:

```python
def extract_work_package_parent_id(work_package: dict) -> int | None:
    parent = (work_package.get("_links") or {}).get("parent") or {}
    return id_from_href(parent.get("href"))
```

Do not derive task hierarchy from the work-package type alone.

For example:

```text
Epic
└── Story
    └── Task
```

is a semantic convention.

The actual provider relationship must be extracted from OpenProject's parent/relationship data.

---

# 17. Attachments Embedded in a Work Package

A work package can contain:

```text
_embedded.attachments
```

Observed structure:

```text
attachments
├── _type = Collection
├── total
├── count
├── _embedded
│   └── elements[]
└── _links
    └── self
```

Each element contains:

```text
id
fileName
fileSize
description
status
contentType
digest
createdAt
_links
```

Example extraction:

```python
def extract_work_package_attachments(work_package: dict) -> list[dict]:
    embedded = work_package.get("_embedded") or {}
    collection = embedded.get("attachments") or {}
    elements = (collection.get("_embedded") or {}).get("elements") or []

    return [
        {
            "id": item.get("id"),
            "file_name": item.get("fileName"),
            "file_size": item.get("fileSize"),
            "content_type": item.get("contentType"),
            "status": item.get("status"),
            "digest_algorithm": (item.get("digest") or {}).get("algorithm"),
            "digest_hash": (item.get("digest") or {}).get("hash"),
            "download_href": (
                (item.get("_links") or {})
                .get("downloadLocation", {})
                .get("href")
            ),
            "created_at": item.get("createdAt"),
        }
        for item in elements
    ]
```

`count == 0` and an empty `elements` array are normal.

---

# 18. Attachment-Created Event

Observed shape:

```text
attachment:created
└── attachment
    ├── id
    ├── fileName
    ├── fileSize
    ├── description
    ├── status
    ├── contentType
    ├── digest
    ├── createdAt
    ├── _embedded
    │   ├── author
    │   └── container
    └── _links
        ├── self
        ├── author
        ├── container
        ├── staticDownloadLocation
        ├── downloadLocation
        └── delete
```

The important relationship is:

```text
attachment._embedded.container
```

In the supplied sample:

```text
container._type = WorkPackage
container.id = 43
container.subject = test
```

Therefore the attachment belongs to Work Package 43.

---

# 19. Attachment Container Must Be Treated Generically

Do not hard-code the assumption that every future attachment belongs to a work package.

Parse:

```python
container = attachment.get("_embedded", {}).get("container")

container_type = container.get("_type") if container else None
container_id = container.get("id") if container else None
```

Then dispatch according to `container_type`.

Example:

```python
if container_type == "WorkPackage":
    ...
else:
    # preserve unknown provider relationship
    ...
```

The observed sample proves `WorkPackage`; it does not prove that no other container types can occur.

---

# 20. Attachment Download

The supplied attachment sample includes:

```text
attachment._links.downloadLocation.href
attachment._links.staticDownloadLocation.href
```

Example:

```text
/api/v3/attachments/3/content
```

Recommended canonical extraction:

```python
links = attachment.get("_links") or {}

download_href = (
    (links.get("downloadLocation") or {}).get("href")
    or (links.get("staticDownloadLocation") or {}).get("href")
)
```

Store the provider-relative link/reference.

Do not assume it is already an absolute URL.

The OpenProject client can resolve it using its configured base URL.

---

# 21. Attachment Ingestion Flow

Recommended Brain flow:

```text
attachment:created
       ↓
extract attachment metadata
       ↓
extract container type + container ID
       ↓
persist external attachment reference
       ↓
policy: should content be ingested?
       ↓
download through OpenProject API
       ↓
document/file parser
       ↓
canonical Document / Artifact
       ↓
link to WorkItem
```

Do not put binary attachment data inside the canonical webhook event.

The webhook event should contain metadata and references.

---

# 22. `project:created`

Minimal event parser:

```python
def parse_project_created(payload: dict) -> dict:
    project = require_dict(payload, "project")

    return {
        "event_type": "ProjectCreated",
        "project": extract_project(project),
    }
```

Root and subproject creation use the same OpenProject action:

```text
project:created
```

Determine whether it is a subproject by the parent relationship.

```python
parent_id = extract_project_parent_id(project)

is_subproject = parent_id is not None
```

Do not create separate parser logic based on a manually supplied label such as `"Sub project"` from logs.

---

# 23. `project:updated`

The supplied `project:updated` examples have the same overall resource structure as project creation.

Important:

The webhook sample does **not include an explicit list of fields that changed**.

Therefore:

```text
action = project:updated
```

means:

```text
the project changed
```

but does not by itself tell the Brain which attribute changed.

Recommended flow:

```text
new provider snapshot
       ↓
load previous normalized snapshot
       ↓
compare fields
       ↓
derive meaningful changes
```

Example:

```python
changes = diff_project(previous, current)
```

Potential derived changes:

```text
name changed
description changed
active changed
parent changed
status explanation changed
```

Do not guess the changed field based on the API action alone.

---

# 24. `work_package:created`

Parse the work package as a full provider snapshot.

Important fields for the Brain:

```text
ID
subject
description
type
project
status
priority
author
assignee
parent
attachments
relations
dates
estimate
completion
```

Recommended canonical event:

```json
{
  "event_type": "WorkItemCreated",
  "source": "openproject",
  "external_id": "43",
  "project_external_id": "8",
  "work_item_type": "Task",
  "title": "test",
  "description": "Description",
  "status": "New",
  "priority": "High"
}
```

---

# 25. Important Created-Event Observation

One supplied `work_package:created` payload has:

```text
createdAt = 2026-09-01T12:01:07.843Z
updatedAt = 2026-09-01T12:02:34.636Z
lockVersion = 1
attachments.count = 1
```

This means the coding agent must not assume that:

```text
action == work_package:created
```

implies:

```text
lockVersion == 0
updatedAt == createdAt
no later relationships are present
```

Treat the action as the provider event trigger and the body as the resource data supplied with that event.

For decisions requiring the latest authoritative state, the adapter may fetch the current work package through OpenProject after the webhook receipt has been persisted.

---

# 26. `work_package:updated`

Use the same work-package extractor as creation.

Do not create two nearly identical resource parsers.

Use:

```python
snapshot = extract_work_package(payload["work_package"])
```

Then map the action separately:

```python
if action == "work_package:created":
    event = WorkItemCreated(...)

elif action == "work_package:updated":
    event = WorkItemChanged(...)
```

For updates, compare the new snapshot with persisted state.

Derived transitions may create more specific canonical events:

```text
assignee changed to Brain
    → WorkItemAssigned

description changed
    → WorkItemChanged

status changed
    → WorkItemStatusChanged

parent changed
    → WorkItemHierarchyChanged

priority changed
    → WorkItemChanged
```

The source provider event and derived canonical event should both remain auditable.

---

# 27. Work-Package Extractor

Example implementation:

```python
def extract_work_package(work_package: dict) -> dict:
    embedded = work_package.get("_embedded") or {}
    links = work_package.get("_links") or {}

    project = embedded.get("project") or {}
    work_type = embedded.get("type") or {}
    priority = embedded.get("priority") or {}
    status = embedded.get("status") or {}
    author = embedded.get("author") or {}
    assignee = embedded.get("assignee")

    parent_link = links.get("parent") or {}

    return {
        "external_id": str(work_package["id"]),
        "lock_version": work_package.get("lockVersion"),

        "subject": work_package.get("subject") or "",
        "description": extract_text(work_package.get("description")),

        "start_date": work_package.get("startDate"),
        "due_date": work_package.get("dueDate"),
        "estimated_time": work_package.get("estimatedTime"),
        "spent_time": work_package.get("spentTime"),
        "percentage_done": work_package.get("percentageDone"),

        "created_at": work_package.get("createdAt"),
        "updated_at": work_package.get("updatedAt"),

        "project": {
            "external_id": str(project["id"]) if project.get("id") is not None else None,
            "identifier": project.get("identifier"),
            "name": project.get("name"),
        },

        "type": {
            "external_id": str(work_type["id"]) if work_type.get("id") is not None else None,
            "name": work_type.get("name"),
        },

        "status": {
            "external_id": str(status["id"]) if status.get("id") is not None else None,
            "name": status.get("name"),
            "closed": status.get("isClosed"),
        },

        "priority": {
            "external_id": str(priority["id"]) if priority.get("id") is not None else None,
            "name": priority.get("name"),
        },

        "author": {
            "external_id": str(author["id"]) if author.get("id") is not None else None,
            "name": author.get("name"),
        },

        "assignee": (
            {
                "external_id": str(assignee["id"]),
                "name": assignee.get("name"),
                "login": assignee.get("login"),
            }
            if assignee and assignee.get("id") is not None
            else None
        ),

        "parent_external_id": (
            str(id_from_href(parent_link.get("href")))
            if id_from_href(parent_link.get("href")) is not None
            else None
        ),

        "attachments": extract_work_package_attachments(work_package),

        "self_href": (links.get("self") or {}).get("href"),
    }
```

---

# 28. Generic Event Envelope Parser

Do not immediately access the resource before validating the outer envelope.

```python
SUPPORTED_ACTIONS = {
    "project:created",
    "project:updated",
    "work_package:created",
    "work_package:updated",
    "attachment:created",
}


def parse_openproject_envelope(payload: dict) -> tuple[str, str, dict]:
    action = payload.get("action")

    if not isinstance(action, str) or not action:
        raise ValueError("Missing OpenProject webhook action")

    if ":" not in action:
        raise ValueError(f"Malformed OpenProject webhook action: {action}")

    resource_name, operation = action.split(":", 1)

    resource_key = {
        "project": "project",
        "work_package": "work_package",
        "attachment": "attachment",
    }.get(resource_name)

    if resource_key is None:
        raise UnsupportedWebhookAction(action)

    resource = payload.get(resource_key)

    if not isinstance(resource, dict):
        raise ValueError(
            f"Expected object at payload[{resource_key!r}] "
            f"for action {action!r}"
        )

    return action, resource_key, resource
```

Do not reject a webhook only because it is not currently routed to an agent workflow.

Unknown actions should be persisted and classified as unsupported so they can be added safely later.

---

# 29. Forward-Compatible Parsing

OpenProject may add fields.

Webhook Pydantic models should therefore avoid rejecting unknown provider fields.

Example:

```python
from pydantic import BaseModel, ConfigDict


class OpenProjectProviderModel(BaseModel):
    model_config = ConfigDict(extra="allow")
```

This lets the adapter explicitly model the fields it needs without breaking when OpenProject adds unrelated fields.

Do not use `extra="forbid"` for the complete provider webhook schema unless a strict-version compatibility policy specifically requires it.

---

# 30. Suggested Provider Models

Use small reusable models.

```python
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class OpenProjectText(ProviderModel):
    format: str | None = None
    raw: str = ""
    html: str = ""


class OpenProjectLink(ProviderModel):
    href: str | None = None
    title: str | None = None
    method: str | None = None
    type: str | None = None
    templated: bool | None = None


class OpenProjectIdentity(ProviderModel):
    id: int
    name: str | None = None


class OpenProjectProject(ProviderModel):
    id: int
    identifier: str
    name: str
    active: bool | None = None
    public: bool | None = None
    description: OpenProjectText | None = None
    createdAt: datetime | None = None
    updatedAt: datetime | None = None

    _embedded: dict[str, Any] | None = None
    _links: dict[str, Any] | None = None
```

For complex HAL sections, it is acceptable initially to type `_embedded` and `_links` as dictionaries while extraction behavior is covered by tests.

Avoid one enormous model that attempts to reproduce every OpenProject API field.

---

# 31. Canonical Event Boundary

Provider parsing should produce provider-neutral data.

Recommended boundary:

```text
OpenProjectWebhookPayload
        ↓
OpenProjectWebhookParser
        ↓
OpenProjectResourceSnapshot
        ↓
OpenProjectNormalizer
        ↓
Brain EventEnvelope + canonical payload
```

Example canonical envelope:

```python
class EventEnvelope(BaseModel):
    event_id: UUID
    event_type: str
    occurred_at: datetime

    project_id: UUID | None

    correlation_id: UUID
    causation_id: UUID | None

    source: str
    payload: dict
```

Example:

```json
{
  "event_type": "WorkItemChanged",
  "source": "openproject",
  "payload": {
    "provider": "openproject",
    "external_id": "40",
    "project_external_id": "3",
    "title": "test4",
    "assignee_external_id": "6"
  }
}
```

No downstream service should need to know:

```text
_embedded
_links
/api/v3/
Faraday
X-OP-Signature
```

---

# 32. External Identity

Provider IDs must not become the Brain's primary internal IDs.

Use an external-reference mapping.

Example:

```text
Brain work_item_id = UUID
provider = openproject
provider_entity = work_package
external_id = 40
```

Recommended key:

```text
(openproject, work_package, 40)
```

Likewise:

```text
(openproject, project, 8)
(openproject, attachment, 3)
(openproject, user, 6)
```

Never use a display title such as:

```text
Infrastructure
test4
brain brain
```

as an identity.

---

# 33. Event Timestamp Selection

The observed resource payloads expose resource timestamps such as:

```text
createdAt
updatedAt
```

These are resource timestamps, not necessarily a unique webhook delivery timestamp.

At webhook receipt, store both:

```text
received_at = Brain server timestamp
resource_created_at = payload createdAt
resource_updated_at = payload updatedAt
```

Do not replace webhook receipt time with `updatedAt`.

---

# 34. Event ID and Idempotency

The supplied samples do not expose a dedicated webhook-delivery ID in the shown JSON body.

Therefore the Brain should generate an internal receipt/event ID.

Example:

```python
event_id = uuid4()
```

Also persist a body digest:

```python
body_sha256 = hashlib.sha256(raw_body).hexdigest()
```

Useful stored metadata:

```text
event_id
provider
action
resource_type
resource_external_id
received_at
body_sha256
processing_status
correlation_id
raw_payload
normalized_payload
```

Do not deduplicate only by:

```text
work_package_id
```

because the same work package generates many valid events.

If exact duplicate deliveries are suppressed, use a deliberate idempotency policy around the raw-body digest/event fingerprint and processing state.

---

# 35. Persist Before Processing

Recommended sequence:

```text
receive HTTP request
     ↓
read exact raw bytes
     ↓
verify signature
     ↓
parse JSON
     ↓
validate minimal envelope
     ↓
persist inbound event + raw payload
     ↓
return successful webhook response
     ↓
asynchronous/internal worker processing
     ↓
normalize
     ↓
state diff
     ↓
canonical events
     ↓
orchestrator
```

This protects against:

```text
worker crash
LLM failure
OpenProject API timeout
database downstream failure
process restart
duplicate delivery
```

The persisted inbound webhook is audit evidence.

---

# 36. Snapshot vs Delta

Treat the supplied OpenProject resources as **snapshots**.

The observed `project:updated` and `work_package:updated` payloads do not contain a reliable generic structure such as:

```json
{
  "changes": {
    "assignee": {
      "old": null,
      "new": 6
    }
  }
}
```

Therefore derive deltas from Brain state:

```python
previous = repository.get_latest_snapshot(
    provider="openproject",
    entity_type="work_package",
    external_id="40",
)

current = extract_work_package(resource)

changes = diff_work_package(previous, current)
```

Example:

```python
if previous.assignee_external_id != current.assignee_external_id:
    emit_assignee_transition(...)
```

This is especially important for orchestrator triggers.

---

# 37. Recommended Work-Package Diff Fields

Initially compare:

```text
subject
description
type
status
priority
project
assignee
responsible
parent
start_date
due_date
estimated_time
percentage_done
attachment IDs
relation IDs
```

Store the normalized snapshot after successfully deriving the transition.

Do not diff unstable provider action links unless an integration feature explicitly depends on them.

---

# 38. Brain Assignment Trigger

The supplied `work_package:updated` sample demonstrates an assignee with:

```text
id = 6
login = brain@...
```

Recommended logic:

```text
work_package:updated
       ↓
normalize snapshot
       ↓
compare previous assignee
       ↓
did assignee transition to configured Brain actor?
       ↓ yes
WorkItemAssigned
       ↓
policy check
       ↓
run task workflow
```

Do not use:

```python
if work_package["_embedded"]["assignee"]["name"] == "brain brain":
```

Use configured provider identity:

```yaml
openproject:
  brain_actor:
    user_id: 6
```

or a resolved persistent external-user mapping.

---

# 39. Prevent Agent Echo Loops

Brain may update a work package or post a comment.

OpenProject may then send another webhook.

Therefore processing must distinguish:

```text
human-originated change
Brain-originated change
other integration-originated change
```

Useful evidence:

```text
author external ID
assignee
outbound operation records
resource version / lockVersion
event timing
correlation metadata maintained internally
```

Do not blindly ignore every webhook authored by the Brain account, because a human may later edit a Brain-created work package.

Instead make outbound operations idempotent and reconcile incoming state.

---

# 40. Resource API Links

Webhook payloads provide useful API references.

For work packages:

```text
_links.self
_links.activities
_links.attachments
_links.relations
_links.updateImmediately
_links.addComment
```

For attachments:

```text
_links.downloadLocation
```

For projects:

```text
_links.self
_links.workPackages
```

The adapter may preserve a small set of operational references:

```python
class ProviderResourceRefs(BaseModel):
    self_href: str | None = None
    activities_href: str | None = None
    attachments_href: str | None = None
```

Do not make domain services execute arbitrary links from payloads.

OpenProject API operations should remain behind an `OpenProjectClient` / work-management port.

---

# 41. Description Extraction

Use a reusable helper:

```python
def extract_raw_text(value: object) -> str:
    if not isinstance(value, dict):
        return ""

    raw = value.get("raw")
    return raw if isinstance(raw, str) else ""
```

Examples:

```python
project_description = extract_raw_text(project.get("description"))

work_item_description = extract_raw_text(
    work_package.get("description")
)

attachment_description = extract_raw_text(
    attachment.get("description")
)
```

This keeps provider formatting logic out of the rest of the system.

---

# 42. Parsing ISO Dates and Durations

Observed dates:

```text
2026-09-01T12:01:07.843Z
2026-09-02T10:17:02.314Z
```

Parse them as timezone-aware UTC datetimes.

Observed durations:

```text
PT0S
```

and fields such as `estimatedTime` may be null.

Do not parse time strings by manually slicing them.

Use a standards-compliant ISO-8601 parser/library or preserve provider strings until the canonical duration layer parses them.

---

# 43. `null` Is Normal

Many valid fields in the samples are null:

```text
startDate
dueDate
estimatedTime
duration
percentageDone
identityUrl
category
responsible
assignee
version
parent
projectPhase
status
```

A missing value is not automatically a malformed event.

Distinguish:

```text
required identity field missing
        → parser error

optional domain field null/missing
        → valid snapshot
```

---

# 44. Missing `_embedded` Is Normal

Example root project creation does not contain an `_embedded` block.

Therefore always write:

```python
embedded = resource.get("_embedded") or {}
```

not:

```python
embedded = resource["_embedded"]
```

Likewise:

```python
links = resource.get("_links") or {}
```

---

# 45. Collections

Observed collection shape:

```json
{
  "_type": "Collection",
  "total": 1,
  "count": 1,
  "_embedded": {
    "elements": []
  },
  "_links": {
    "self": {
      "href": "..."
    }
  }
}
```

Reusable extraction:

```python
def collection_elements(collection: dict | None) -> list[dict]:
    if not collection:
        return []

    embedded = collection.get("_embedded") or {}
    elements = embedded.get("elements")

    if not isinstance(elements, list):
        return []

    return [
        element
        for element in elements
        if isinstance(element, dict)
    ]
```

---

# 46. User Extraction

User payloads may appear as:

```text
author
assignee
```

Recommended normalized provider-user reference:

```python
def extract_user(user: dict | None) -> dict | None:
    if not user:
        return None

    if user.get("id") is None:
        return None

    return {
        "external_id": str(user["id"]),
        "name": user.get("name"),
        "login": user.get("login"),
        "email": user.get("email"),
        "status": user.get("status"),
    }
```

Avoid propagating unnecessary personal/user-profile fields into every canonical event.

Only retain what the Brain actually needs for identity, audit, attribution, and routing.

---

# 47. Sensitive/Unnecessary Provider Data

Webhook payloads may contain:

```text
email
avatar
admin flag
login
membership links
delete/update links
cost information
```

Apply data minimization.

For example, a planning agent normally needs:

```text
author ID
author display name
assignee ID
assignee display name
```

It normally does not need:

```text
avatar URL
account-management links
user deletion links
```

Keep the raw webhook in restricted audit storage if required, but do not unnecessarily copy all provider fields into semantic stores or LLM context.

---

# 48. Attachment Hashes

Observed attachment metadata includes:

```json
"digest": {
  "algorithm": "md5",
  "hash": "..."
}
```

Treat this as **provider-supplied file metadata**.

Do not use a provider MD5 digest as a security trust decision.

For Brain ingestion/deduplication, it is reasonable to calculate an internal stronger content digest after download, for example:

```text
sha256
```

and preserve both:

```text
provider_digest
brain_content_digest
```

---

# 49. Work-Package Attachment Events Can Overlap

The samples demonstrate two ways attachment information reaches the Brain:

```text
attachment:created
```

and:

```text
work_package._embedded.attachments
```

Do not create two internal files for the same provider attachment.

Use provider identity:

```text
(openproject, attachment, attachment_id)
```

and upsert.

Example:

```text
attachment:created id=3
       ↓
Attachment external ref 3 created

later work-package snapshot contains attachment id=3
       ↓
same external ref
       ↓
update/reconcile, do not duplicate
```

---

# 50. Suggested Canonical Models

## 50.1 External reference

```python
class ExternalReference(BaseModel):
    provider: str
    entity_type: str
    external_id: str
```

## 50.2 Project

```python
class CanonicalProjectSnapshot(BaseModel):
    external_ref: ExternalReference

    identifier: str
    name: str
    description: str = ""

    active: bool | None = None
    public: bool | None = None

    parent_external_id: str | None = None
    ancestor_external_ids: list[str] = []

    created_at: datetime | None = None
    updated_at: datetime | None = None
```

## 50.3 Work item

```python
class CanonicalWorkItemSnapshot(BaseModel):
    external_ref: ExternalReference

    project_external_id: str

    type_external_id: str | None = None
    type_name: str | None = None

    subject: str
    description: str = ""

    status_external_id: str | None = None
    status_name: str | None = None

    priority_external_id: str | None = None
    priority_name: str | None = None

    author_external_id: str | None = None
    assignee_external_id: str | None = None

    parent_external_id: str | None = None

    attachment_external_ids: list[str] = []

    lock_version: int | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None
```

## 50.4 Attachment

```python
class CanonicalAttachmentSnapshot(BaseModel):
    external_ref: ExternalReference

    file_name: str
    content_type: str | None = None
    file_size: int | None = None

    container_type: str | None = None
    container_external_id: str | None = None

    author_external_id: str | None = None

    provider_download_href: str | None = None

    provider_digest_algorithm: str | None = None
    provider_digest_hash: str | None = None

    created_at: datetime | None = None
```

---

# 51. Event Mapping for the Brain

Suggested mapping:

| OpenProject event | Canonical initial event |
|---|---|
| `project:created` | `ProjectCreated` |
| `project:updated` | `ProjectChanged` |
| `work_package:created` | `WorkItemCreated` |
| `work_package:updated` | `WorkItemChanged` |
| `attachment:created` | `AttachmentCreated` |

Then derive semantic events from state transitions.

Example:

```text
OpenProject:
work_package:updated
        ↓
normalizer:
WorkItemChanged
        ↓
state differ:
assignee null → Brain
        ↓
derived event:
WorkItemAssigned
```

This separation is important.

Provider actions describe **what OpenProject emitted**.

Canonical events describe **what the Brain understands happened**.

---

# 52. Recommended Parser Module Layout

```text
brain/
└── adapters/
    └── openproject/
        ├── webhook_models.py
        ├── webhook_parser.py
        ├── extractors.py
        ├── normalizer.py
        ├── signature.py
        ├── client.py
        └── mappings.py
```

Responsibilities:

```text
webhook_models.py
    minimal provider data models

signature.py
    transport signature verification

webhook_parser.py
    parse/validate event envelope

extractors.py
    project/work-package/attachment extraction

normalizer.py
    provider snapshot → canonical models/events

mappings.py
    type/status/priority/provider mapping

client.py
    follow-up OpenProject API operations
```

Do not place OpenProject JSON traversal inside the orchestrator.

---

# 53. Recommended Processing Service

```python
class OpenProjectWebhookService:
    def __init__(
        self,
        event_repository,
        normalizer,
        dispatcher,
    ):
        self.event_repository = event_repository
        self.normalizer = normalizer
        self.dispatcher = dispatcher

    async def receive(
        self,
        raw_body: bytes,
        headers,
    ) -> str:
        # 1. verify transport
        verify_openproject_signature(
            raw_body,
            headers.get("x-op-signature"),
        )

        # 2. parse JSON
        payload = json.loads(raw_body)

        # 3. validate minimal provider envelope
        action, resource_key, resource = (
            parse_openproject_envelope(payload)
        )

        # 4. persist exact inbound event
        event_id = await self.event_repository.store_inbound(
            provider="openproject",
            action=action,
            raw_body=raw_body,
            payload=payload,
        )

        # 5. enqueue/dispatch using persisted event ID
        await self.dispatcher.enqueue(event_id)

        return event_id
```

Normalization can occur in the worker so receiving the webhook remains fast and recoverable.

---

# 54. Worker Parsing

Example:

```python
async def process_openproject_event(event_id: UUID) -> None:
    inbound = await event_repository.get(event_id)

    action, _, resource = parse_openproject_envelope(
        inbound.payload
    )

    normalized = normalizer.normalize(
        action=action,
        resource=resource,
    )

    previous = await snapshot_repository.get_previous(
        normalized.external_ref
    )

    changes = snapshot_differ.diff(
        previous=previous,
        current=normalized,
    )

    canonical_events = derive_events(
        action=action,
        previous=previous,
        current=normalized,
        changes=changes,
    )

    await snapshot_repository.upsert(normalized)

    for event in canonical_events:
        await canonical_event_bus.publish(event)
```

---

# 55. Error Classification

Do not mark every failure as the same error.

Recommended classes:

```text
WebhookAuthenticationError
MalformedWebhookError
UnsupportedWebhookAction
ProviderPayloadError
NormalizationError
ProviderApiError
PersistenceError
ProcessingError
```

Example behavior:

```text
invalid signature
    → reject HTTP request

malformed JSON
    → reject HTTP request

valid JSON, unsupported action
    → persist if policy allows
    → mark unsupported
    → no agent workflow

valid known action but downstream failure
    → event remains persisted
    → retry worker
```

---

# 56. Minimum Validation Per Event

## `project:created` / `project:updated`

Require:

```text
action
project.id
project.identifier
project.name
```

## `work_package:created` / `work_package:updated`

Require:

```text
action
work_package.id
work_package.subject
```

Strongly expect/validate when available:

```text
_embedded.project.id
_embedded.type
_embedded.status
```

If critical context is missing, persist the webhook and enrich using `_links.self` / OpenProject API instead of crashing due to optional nested fields.

## `attachment:created`

Require:

```text
action
attachment.id
attachment.fileName
```

For ingestion, also require or resolve:

```text
container
downloadLocation
```

---

# 57. Provider Enrichment

A webhook should trigger enrichment only when required.

Example:

```text
work package webhook already contains:
project
type
status
priority
assignee

        ↓

no need to GET work package just to read these again
```

Fetch current provider state when:

```text
critical required field is missing
exact latest state is required
relationship details are incomplete
activities/comments must be examined
attachment content must be downloaded
```

This keeps webhook processing efficient and reduces provider API load.

---

# 58. Handling OpenProject Project Hierarchy

Store project hierarchy canonically:

```text
Project UUID
external OpenProject project ID
parent Project UUID
ancestor path optionally derived
```

Do not store only:

```text
project._links.ancestors titles
```

Recommended reconciliation:

```text
OpenProject project 8
parent external id 4
        ↓
external mapping lookup
        ↓
Brain project UUID for OpenProject project 4
        ↓
canonical parent_project_id
```

If the parent has not yet been ingested:

```text
store unresolved ExternalReference
        ↓
resolve later
```

Do not reject project 8 because project 4 is temporarily absent from the Brain database.

---

# 59. Relation Between Project and Work Package

For a work-package webhook, the project appears in:

```text
work_package._embedded.project
```

and as a link:

```text
work_package._links.project
```

The canonical relationship is:

```text
Project
└── WorkItem
```

Example:

```text
OpenProject Project 8: Infrastructure
└── WorkPackage 43: test
```

Use project ID `8`, not project title `Infrastructure`, to create the provider relationship.

---

# 60. Important Distinction: Project Hierarchy vs Work-Item Hierarchy

These are separate graphs.

## Project hierarchy

```text
Odoo deployment
└── Project 2
    └── Infrastructure
```

Derived from:

```text
project parent
project ancestors
```

## Work-item hierarchy

Example semantic structure:

```text
Epic
└── Story
    └── Task
```

Derived from:

```text
work_package parent
work_package relations
work_package type
```

Do not merge these hierarchies.

A Task belongs to a Project, while also optionally belonging under another Work Package.

---

# 61. Suggested Database Snapshot Records

Provider snapshot table:

```text
external_resource_snapshots
---------------------------
id
provider
entity_type
external_id
resource_version
resource_updated_at
received_at
normalized_json
raw_event_id
created_at
```

External mapping:

```text
external_references
-------------------
id
provider
entity_type
external_id
internal_entity_type
internal_entity_id
created_at
updated_at
```

Inbound event:

```text
event_log
---------
event_id
provider
provider_action
resource_type
resource_external_id
received_at
body_sha256
raw_payload
normalized_payload
status
attempt_count
correlation_id
last_error
```

Exact table names should follow the existing repository architecture.

---

# 62. Tests the Coding Agent Must Add

Create fixture payloads for every observed shape.

## 62.1 Project created — root

Assert:

```text
project ID parsed
identifier parsed
parent = None
ancestors = []
```

## 62.2 Project created — subproject

Assert:

```text
project ID = child
parent ID extracted
ancestor IDs extracted in correct order
```

## 62.3 Project updated

Assert:

```text
same extractor works
previous/current snapshots produce expected diff
```

## 62.4 Work package created without assignee

Assert:

```text
assignee = None
parser does not fail
```

## 62.5 Work package created with attachment

Assert:

```text
attachment ID parsed
file metadata parsed
project/type/status/priority parsed
```

## 62.6 Work package updated with assignee

Assert:

```text
assignee ID parsed
transition null → Brain emits WorkItemAssigned
same assignee repeated does not emit duplicate assignment transition
```

## 62.7 Attachment created

Assert:

```text
attachment metadata parsed
container type = WorkPackage
container ID parsed
download href parsed
```

## 62.8 Missing optional `_embedded`

Assert parser remains valid.

## 62.9 Unknown extra fields

Assert parser remains valid.

## 62.10 Invalid signature

Assert request rejected before processing.

## 62.11 Duplicate webhook body

Assert side effects are idempotent.

---

# 63. Golden Fixtures

Keep sanitized copies of the observed payloads in the repository.

Suggested structure:

```text
tests/
└── fixtures/
    └── openproject/
        ├── project_created_root.json
        ├── project_created_subproject.json
        ├── project_updated.json
        ├── work_package_created_empty.json
        ├── work_package_created_attachment.json
        ├── work_package_updated_assigned.json
        └── attachment_created_work_package.json
```

Do not keep Python `repr()` logs as the canonical fixtures.

Convert the request bodies to valid JSON.

Redact environment-specific or sensitive data where necessary while preserving schema shape.

---

# 64. Parser Contract Tests

The OpenProject adapter should expose a contract similar to:

```python
class WorkManagementWebhookAdapter(Protocol):
    def parse(
        self,
        raw_payload: bytes,
        headers: Mapping[str, str],
    ) -> list[CanonicalEvent]:
        ...
```

OpenProject-specific tests validate payload interpretation.

Provider-neutral application tests validate only canonical events.

This keeps future Jira or other work-management integrations replaceable.

---

# 65. What Must Not Leak Outside the Adapter

The following should not appear in domain/application service code:

```text
"_embedded"
"_links"
"work_package"
"/api/v3/work_packages/"
"x-op-signature"
OpenProject numeric type IDs
OpenProject numeric status IDs
OpenProject HAL action links
```

Downstream code should receive:

```text
ProjectCreated
ProjectChanged
WorkItemCreated
WorkItemChanged
WorkItemAssigned
AttachmentCreated

ProjectSnapshot
WorkItemSnapshot
AttachmentSnapshot
ExternalReference
```

---

# 66. Parsing Decision Tree

```text
Incoming request
      │
      ├─ signature invalid?
      │      └─ reject
      │
      ▼
JSON parse
      │
      ├─ invalid?
      │      └─ reject
      │
      ▼
read action
      │
      ├─ project:created
      │      └─ parse project
      │
      ├─ project:updated
      │      └─ parse project → diff old/new
      │
      ├─ work_package:created
      │      └─ parse work package
      │
      ├─ work_package:updated
      │      └─ parse work package → diff old/new
      │
      ├─ attachment:created
      │      └─ parse attachment + container
      │
      └─ unknown
             └─ persist as unsupported
```

---

# 67. Example End-to-End Normalization

Input:

```json
{
  "action": "work_package:updated",
  "work_package": {
    "id": 40,
    "subject": "test4",
    "_embedded": {
      "project": {
        "id": 3,
        "identifier": "odoo-deployment",
        "name": "Odoo deployment"
      },
      "type": {
        "id": 1,
        "name": "Task"
      },
      "status": {
        "id": 1,
        "name": "New"
      },
      "priority": {
        "id": 8,
        "name": "Normal"
      },
      "assignee": {
        "id": 6,
        "name": "brain brain"
      }
    }
  }
}
```

Provider snapshot:

```json
{
  "provider": "openproject",
  "external_id": "40",
  "project_external_id": "3",
  "type_name": "Task",
  "subject": "test4",
  "status_name": "New",
  "priority_name": "Normal",
  "assignee_external_id": "6"
}
```

Previous snapshot:

```json
{
  "external_id": "40",
  "assignee_external_id": null
}
```

Derived canonical events:

```text
WorkItemChanged
WorkItemAssigned
```

The orchestrator reacts to `WorkItemAssigned`, not directly to OpenProject's nested JSON.

---

# 68. Example Attachment Normalization

Input relation:

```text
attachment id = 3
container type = WorkPackage
container id = 43
```

Canonical result:

```json
{
  "provider": "openproject",
  "external_id": "3",
  "file_name": "Screenshot_2026-04-27_224250.png",
  "content_type": "image/png",
  "container_type": "work_item",
  "container_external_id": "43",
  "download_href": "/api/v3/attachments/3/content"
}
```

Then resolve:

```text
(openproject, work_package, 43)
        ↓
Brain WorkItem UUID
```

and link the ingested document/artifact to that internal WorkItem.

---

# 69. Logging

Useful structured log fields:

```text
event_id
correlation_id
provider
provider_action
resource_type
resource_external_id
project_external_id
processing_stage
status
attempt
```

Example:

```python
logger.info(
    "OpenProject webhook normalized",
    extra={
        "event_id": str(event_id),
        "provider_action": action,
        "resource_type": resource_type,
        "resource_external_id": external_id,
        "project_external_id": project_external_id,
    },
)
```

Avoid logging the entire webhook at INFO level in production.

The raw event may contain:

```text
user email
attachment names
project information
task descriptions
internal URLs
```

Store full raw payload only in the appropriate restricted audit store.

---

# 70. Coding-Agent Implementation Rules

The coding agent should follow these rules while implementing the OpenProject webhook adapter:

1. Verify signatures using exact raw request bytes.
2. Parse actual JSON; do not parse copied Python dictionary logs.
3. Persist the inbound event before expensive processing.
4. Route using `action`.
5. Select the primary resource from the action.
6. Treat `_embedded` as optional.
7. Treat nested resources such as `assignee` as optional.
8. Use provider IDs for external identity.
9. Do not use names/titles as IDs.
10. Do not hard-code OpenProject type/status/priority numeric IDs.
11. Prefer direct fields, then embedded resource, then link reference.
12. Parse IDs from links only as a fallback/reference mechanism.
13. Normalize OpenProject data before domain/application logic.
14. Store provider and canonical IDs separately.
15. Treat update payloads as snapshots, then compute meaningful deltas.
16. Detect assignment transitions from old vs new state.
17. Upsert attachments by provider attachment ID.
18. Keep project hierarchy separate from work-item hierarchy.
19. Minimize provider/user data copied into agent context.
20. Keep `_links` operations behind the OpenProject client/adapter.
21. Preserve unknown fields for compatibility where useful, but ignore them in canonical extraction unless needed.
22. Keep webhook processing idempotent.
23. Add golden tests for every observed event shape.
24. Never let an unsupported event crash the webhook receiver.
25. Record unsupported events for later inspection.

---

# 71. Recommended Initial Implementation Scope

Implement support for these observed actions first:

```text
project:created
project:updated
work_package:created
work_package:updated
attachment:created
```

Core extractors:

```text
extract_project()
extract_project_parent()
extract_project_ancestors()

extract_work_package()
extract_work_package_parent_id()
extract_work_package_attachments()
extract_assignee()

extract_attachment()
extract_attachment_container()

extract_user()
extract_raw_text()
id_from_href()
collection_elements()
```

Core normalization:

```text
project:created
    → ProjectCreated

project:updated
    → ProjectChanged

work_package:created
    → WorkItemCreated

work_package:updated
    → WorkItemChanged
    → optionally derive WorkItemAssigned / other transitions

attachment:created
    → AttachmentCreated
```

---

# 72. Future Events

The parser should be easy to extend when additional OpenProject actions are captured, for example events involving:

```text
comments / activities
relations
membership/user changes
work-package deletion
attachment deletion
status changes represented through work-package updates
```

Do not invent their payload schemas before observing or verifying them.

Add each new provider payload as a fixture and extend the adapter incrementally.

---

# 73. Final Architecture

```text
                    OpenProject
                         │
                         │ HTTP webhook
                         ▼
                Webhook API endpoint
                         │
                         ├── raw bytes
                         ├── X-OP-Signature
                         ▼
                Signature verifier
                         │
                         ▼
                   JSON decoder
                         │
                         ▼
              Minimal envelope parser
                         │
                         ▼
                 Inbound event log
                         │
                         ▼
                OpenProject parser
                  /       |       \
                 /        |        \
          Project      WorkPackage  Attachment
             │             │           │
             ▼             ▼           ▼
         provider snapshots / external refs
                         │
                         ▼
                    state differ
                         │
                         ▼
                 canonical normalizer
                         │
          ┌──────────────┼─────────────────┐
          ▼              ▼                 ▼
   ProjectChanged   WorkItemChanged   AttachmentCreated
                         │
                         ├── WorkItemAssigned
                         ├── status transition
                         ├── hierarchy transition
                         └── content transition
                         │
                         ▼
                 Brain event bus
                         │
                         ▼
                  Orchestrator
                         │
             ┌───────────┼───────────┐
             ▼           ▼           ▼
          Planning     Coding    Verification
```

The central rule is:

> **OpenProject webhook JSON is integration data, not Brain domain data. Parse it once at the provider boundary, preserve enough raw data for audit/recovery, normalize it into stable canonical models, and let every downstream component depend only on those canonical models.**
