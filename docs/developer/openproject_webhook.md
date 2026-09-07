# OpenProject Webhook Implementation Analysis and Generic Adapter Design

## 1. Scope

This document compares the captured-payload guide in
`docs/tools/OPENPROJECT_WEBHOOK_DATA_STRUCTURE_AND_PARSING.md` with the current
implementation in:

- `brain/api/routes/webhooks.py`
- `brain/api/auth.py`
- `brain/adapters/work_management/openproject.py`
- `brain/adapters/work_management/openproject_http.py`
- `brain/ports/work_management.py`
- `brain/domain/events.py`
- `brain/domain/work_management.py`
- `tests/test_phase34_openproject.py`
- `tests/test_phase40_hardening.py`

It also proposes a provider-neutral webhook boundary so OpenProject, Jira,
GitLab, or another tool can be replaced without changing application workflows.

## 2. Executive conclusion

The current endpoint is a narrow prototype. It authenticates an OpenProject
request, extracts a few work-package fields, publishes one canonical event, and
may enqueue a work-item run. It does **not** implement the payload model or the
processing guarantees described by the parsing guide.

The largest architectural problem is that the FastAPI route itself knows
OpenProject JSON keys and workflow rules. Provider-specific details such as
`action`, `work_package`, assignee links, and comment shapes should live in an
OpenProject webhook adapter. The route should only collect raw HTTP data and
invoke a provider-neutral ingress service.

The recommended design is:

```text
POST /api/v1/webhooks/{provider}
        |
        v
WebhookIngressService
        |
        +--> WebhookAdapterRegistry --> provider adapter verifies/describes request
        |
        +--> InboundWebhookRepository (persist exact receipt)
        |
        +--> CommandQueue(ProcessWebhookCommand)
                               |
                               v
                     WebhookProcessingService
                               |
                               +--> provider adapter normalizes payload
                               +--> snapshot repository + state differ
                               +--> canonical EventEnvelope objects
                               +--> application handlers/orchestrator
```

`WorkManagementPort` should remain responsible for querying and updating work
items. Webhook parsing is a separate boundary because one webhook provider can
emit projects, work packages, attachments, users, comments, and other resource
types.

## 3. Current implementation flow

The current `openproject_webhook()` function at
`brain/api/routes/webhooks.py:38-95` performs all of the following in one API
function:

1. Runs `verify_webhook("openproject")` as a FastAPI dependency.
2. Parses the request body directly with `request.json()`.
3. Reads `action`, with a fallback to `event_type`.
4. Always selects `work_package`/`workPackage` as the resource.
5. Maps only `work_package:created` and `work_package:updated`.
6. Defaults every unrecognized action to `WORK_ITEM_CHANGED`.
7. Extracts only ID, subject, direct status, and a direct assignee link.
8. Publishes an `EventEnvelope` to the in-memory event bus.
9. If a top-level comment/activity exists, emits human feedback and returns.
10. Otherwise, if the current assignee equals the configured Brain actor,
    creates a canonical work item and enqueues `RunWorkItemCommand`.

This mixes HTTP ingress, provider authentication, provider parsing,
normalization, persistence lookup, canonical entity creation, transition
inference, and workflow triggering.

## 4. Comparison with the captured-payload guide

| Concern | Parsing guide | Current implementation | Assessment |
|---|---|---|---|
| Action field | Uses top-level `action` (`:54-89`, `:1397-1440`) | Reads `action` (`webhooks.py:47`) | Aligned after the recent change |
| Signature header | `X-OP-Signature` / `x-op-signature` (`:92-102`, `:146-188`) | Reads `x-op-signature` (`auth.py:84`) | Aligned |
| Signature algorithm | Observed `sha1=<hex>` over exact raw bytes | Uses HMAC-SHA1 over exact raw bytes (`auth.py:86-92`) | Aligned with captured payloads |
| Supported actions | Project create/update, work-package create/update, attachment create (`:42-89`) | Only work-package create/update (`webhooks.py:31-34`) | Major gap |
| Resource selection | Derive resource key from action (`:1397-1440`) | Always reads `work_package` | Incorrect for project/attachment events |
| Unknown actions | Persist and classify unsupported (`:1442-1445`) | Silently converts to `WORK_ITEM_CHANGED` | Incorrect and unsafe |
| Minimal validation | Validate action and required fields (`:2529-2577`) | No explicit validation | Missing |
| Direct fields | Use as primary values | Reads ID and subject | Partial |
| Rich text | Read `description.raw` (`:381-413`, `:1931-1958`) | Description is not normalized in webhook route | Missing |
| `_embedded` | Optional source for project/type/status/priority/author/assignee | Not read | Missing |
| `_links` | Fallback references and relationship IDs | Only expects a non-observed direct `assignee.href` shape | Incorrect shape |
| Assignee | Prefer `_embedded.assignee.id`, fall back to `_links.assignee.href` (`:799-860`) | Reads `work_package.assignee.href` (`webhooks.py:202-208`) | Does not parse captured payload |
| Status | `_embedded.status.id/name/isClosed` | Reads direct `work_package.status` | Does not parse captured payload |
| Type and priority | Extract names/IDs and map by configuration | Not extracted | Missing |
| Project relationship | Extract `_embedded.project` or `_links.project` | Not extracted | Missing; causes arbitrary project selection |
| Parent relationship | Parse `_links.parent.href` | Not extracted | Missing |
| Attachments | Normalize metadata and container relation | Not supported | Missing |
| Project hierarchy | Parse parent and ancestors | Not supported | Missing |
| Snapshot semantics | Store normalized snapshot and derive a delta (`:1742-1808`) | No snapshots or differ | Missing |
| Assignment event | Emit only on transition to Brain (`:1812-1853`) | Triggers whenever payload appears assigned to Brain | Duplicate execution risk |
| Echo-loop prevention | Reconcile outbound and inbound operations (`:1857-1885`) | None | Missing |
| External identity | Key by provider, entity type, external ID (`:1587-1624`) | Work items store a ref, but lookups scan all projects and ignore entity type | Partial |
| Idempotency | Persist digest/fingerprint and suppress exact duplicate side effects | Not used | Missing |
| Persist before process | Store exact inbound receipt, then enqueue worker (`:1697-1738`) | Performs processing inline and publishes to an in-memory bus | Missing |
| Logging | Structured metadata; do not log full body at INFO (`:3109-3153`) | Logs the entire body and signature | Security/privacy issue |
| Provider boundary | OpenProject parsing remains in adapter (`:2930-2959`) | Parsing is in API route | Architectural violation |

## 5. Detailed implementation findings

### 5.1 Project creation is currently misclassified

For this payload:

```json
{
  "action": "project:created",
  "project": {
    "id": 8,
    "identifier": "infrastructure",
    "name": "Infrastructure"
  }
}
```

current code:

1. reads `action = "project:created"`;
2. ignores `project` and creates an empty `work_package` dictionary;
3. defaults the unknown action to `WORK_ITEM_CHANGED`;
4. publishes a work-item event with `external_id = ""`.

The expected result is `ProjectCreated` with an OpenProject project external
reference and normalized project snapshot.

### 5.2 Captured work-package assignments are not parsed

The guide shows an assigned user at:

```text
work_package._embedded.assignee.id
```

with fallback at:

```text
work_package._links.assignee.href
```

Current `_assignee_id()` only reads:

```text
work_package.assignee.href
```

Consequently, the assignment automation will not trigger for the observed real
payload structure.

### 5.3 Every assigned update can trigger another execution

The guide requires comparing the previous and current snapshots:

```text
previous assignee != Brain
current assignee == Brain
    -> WorkItemAssigned
```

Current code checks only the current payload. A status change, description
change, comment, or unrelated update on a work package already assigned to Brain
can enqueue another `RunWorkItemCommand`.

### 5.4 `_find_or_create_work_item()` always creates

Despite its name, `brain/api/routes/webhooks.py:218-242` does not search for an
existing work item. It selects the first canonical project and creates a new
work item on every trigger.

This can produce:

- duplicate canonical work items;
- duplicate external mappings;
- duplicate execution commands;
- association with the wrong project.

The existing work-management mapping repository supports lookup from internal
work-item ID to provider, but it lacks a reverse lookup such as:

```python
get_by_external_ref(provider, entity_type, external_id)
```

That reverse lookup should be added to the relevant port and adapter rather than
scanning all projects and work items.

### 5.5 Inbound events are not durable

The route publishes directly to `container.event_bus`, which is currently an
`InMemoryEventBus`. The event is not persisted through the existing
`EventLogRepository`, and it is not visible to another process.

The repository already has useful pieces:

- `IdempotencyStore` in `brain/ports/idempotency.py`;
- `EventLogRepository` in `brain/ports/event_log.py`;
- PostgreSQL implementations for both;
- Redis `CommandQueue` for cross-process work.

However, a raw inbound webhook is not the same as a canonical event. A separate
`InboundWebhookRepository` is recommended so provider payloads do not pollute
the canonical event log.

### 5.6 Database transaction boundary is missing

PostgreSQL repositories flush but deliberately do not commit. The API route does
not use `PostgresUnitOfWork` or another request transaction. The work item and
mapping created before queueing may therefore be invisible to a separate worker
and may be rolled back when the API session closes.

Ingress persistence, idempotency registration, and command enqueue need an
explicit reliability policy. A transactional outbox is ideal; at minimum,
commit the receipt before acknowledging the webhook and make command enqueue
idempotent/recoverable.

### 5.7 Human feedback does not resume a workflow

`_normalize_human_comment()` calls `HumanFeedbackService.receive()`. That method
emits an in-memory `HUMAN_FEEDBACK_RECEIVED` event but does not invoke
`resume_workflow()`, invalidate context, or enqueue a resume command. The helper
docstring therefore overstates the current behavior.

Comments/activities were listed as future payloads in the parsing guide. They
should be implemented only after captured examples define their actual shape.

### 5.8 Event trigger provenance is wrong

`enqueue_command()` defaults to `TriggerType.USER`. The webhook route does not
pass `TriggerType.EVENT`, so commands initiated by OpenProject are incorrectly
classified as user-triggered.

### 5.9 Sensitive data is logged and returned

Current code includes:

- `LOGGER.info(f"openproject_webhook: {body=}")`;
- `LOGGER.info(f"{signature=}")`;
- an authentication error containing all request headers and raw body;
- module-level `logging.basicConfig(...)` in a route module.

OpenProject payloads can contain names, email addresses, internal URLs, task
descriptions, attachment names, and other sensitive project data. Authentication
errors should never echo signatures, headers, secrets, or raw bodies to callers.
Log only bounded metadata such as correlation ID, provider, action, external
resource ID, body digest, processing stage, and error category.

`logging.basicConfig()` belongs in runtime entry points, not imported route
modules.

### 5.10 Tests no longer match authentication or captured payloads

The current implementation expects:

```text
X-OP-Signature: sha1=<HMAC-SHA1>
action: work_package:updated
```

The existing tests still send:

```text
X-OpenProject-Signature: sha256=<HMAC-SHA256>
eventType: work_package:updated
```

Verification command:

```text
uv run pytest -q tests/test_phase34_openproject.py tests/test_phase40_hardening.py -q
```

Result at the time of this analysis:

```text
4 failed, 12 passed
```

The four failures are all signature-contract mismatches. More importantly, the
test payloads are synthetic and do not exercise the captured `_embedded` and
`_links` structures. The golden fixtures requested by the guide are absent.

## 6. Why `WorkManagementPort` is not enough

`WorkManagementPort` correctly abstracts outbound/query operations:

- fetch a work item;
- list changed work items;
- publish a work item or status;
- post execution results;
- link a pull request.

Webhook ingestion has different responsibilities:

- authenticate provider-specific HTTP delivery;
- recognize provider action and resource type;
- validate minimal payload shape;
- preserve exact receipt data;
- normalize several resource types;
- classify unsupported actions;
- produce one or more canonical events.

Adding all of this to `WorkManagementPort` would violate interface segregation
and would not fit tools such as GitLab, XWiki, or Backstage. Introduce a separate
webhook port and let a provider plugin implement one or both ports as needed.

## 7. Proposed provider-neutral contracts

Suggested module: `brain/ports/webhooks.py`.

```python
from collections.abc import Mapping
from typing import Protocol


class WebhookAuthenticationError(Exception): ...
class MalformedWebhookError(Exception): ...
class UnsupportedWebhookAction(Exception): ...


class WebhookDescriptor(BaseModel):
    provider: str
    provider_action: str
    resource_type: str
    resource_external_id: str | None = None
    resource_version: str | None = None
    resource_updated_at: datetime | None = None


class WebhookNormalization(BaseModel):
    descriptor: WebhookDescriptor
    snapshot: ExternalResourceSnapshot | None = None
    canonical_events: list[EventEnvelope] = Field(default_factory=list)
    unsupported: bool = False


class WebhookAdapter(Protocol):
    @property
    def provider(self) -> str: ...

    def authenticate(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> None: ...

    def describe(self, *, raw_body: bytes) -> WebhookDescriptor: ...

    def normalize(self, *, raw_body: bytes) -> WebhookNormalization: ...


class WebhookAdapterRegistry(Protocol):
    def get(self, provider: str) -> WebhookAdapter | None: ...
```

The adapter receives resolved credentials in its constructor. It must not read
environment variables itself.

`describe()` performs only enough parsing to validate and persist the receipt.
`normalize()` performs provider-specific extraction. It can be called later by a
worker using the persisted raw bytes.

## 8. Proposed provider-neutral persistence models

Suggested module: `brain/domain/webhooks.py`.

```python
class InboundWebhookStatus(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    PROCESSING = "processing"
    PROCESSED = "processed"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class InboundWebhook(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    provider: str
    provider_action: str
    resource_type: str
    resource_external_id: str | None = None
    received_at: datetime
    correlation_id: UUID
    body_sha256: str
    raw_body: bytes | None = None
    raw_payload: dict[str, object] | None = None
    status: InboundWebhookStatus = InboundWebhookStatus.RECEIVED
    attempt_count: int = 0
    last_error: str | None = None
```

Raw payload retention must follow a configured security/retention policy. For
large or sensitive payloads, store encrypted object content and keep only an
artifact URI and digest in PostgreSQL.

Suggested port:

```python
class InboundWebhookRepository(Protocol):
    async def create(self, receipt: InboundWebhook) -> InboundWebhook: ...
    async def get(self, receipt_id: UUID) -> InboundWebhook | None: ...
    async def find_duplicate(self, provider: str, body_sha256: str) -> InboundWebhook | None: ...
    async def update_status(...) -> None: ...
```

Use a separate provider-neutral snapshot identity:

```text
(provider, entity_type, external_id)
```

and a snapshot record containing provider version, resource timestamp, receipt
time, normalized data, and inbound receipt ID.

## 9. Generic ingress service

Suggested module: `brain/application/webhook_ingress.py`.

```python
class WebhookIngressService:
    def __init__(self, adapters, receipts, idempotency, queue):
        self.adapters = adapters
        self.receipts = receipts
        self.idempotency = idempotency
        self.queue = queue

    async def receive(
        self,
        *,
        provider: str,
        raw_body: bytes,
        headers: Mapping[str, str],
        correlation_id: UUID,
    ) -> InboundWebhook:
        adapter = self.adapters.get(provider)
        if adapter is None:
            raise UnknownWebhookProvider(provider)

        adapter.authenticate(raw_body=raw_body, headers=headers)
        descriptor = adapter.describe(raw_body=raw_body)
        digest = sha256(raw_body).hexdigest()
        idempotency_key = f"webhook:{provider}:{digest}"

        duplicate = await self.receipts.find_duplicate(provider, digest)
        if duplicate is not None:
            return duplicate

        receipt = await self.receipts.create(
            InboundWebhook(
                provider=provider,
                provider_action=descriptor.provider_action,
                resource_type=descriptor.resource_type,
                resource_external_id=descriptor.resource_external_id,
                received_at=datetime.now(UTC),
                correlation_id=correlation_id,
                body_sha256=digest,
                raw_body=raw_body,
            )
        )

        await self.queue.enqueue_process_webhook(receipt.id, correlation_id)
        return receipt
```

For strict delivery guarantees, use a PostgreSQL transactional outbox instead
of attempting an atomic transaction across PostgreSQL and Redis.

## 10. Thin generic HTTP route

The API route should not inspect provider JSON:

```python
@router.post("/api/v1/webhooks/{provider}", status_code=202)
async def receive_webhook(provider: str, request: Request) -> AcceptedWebhook:
    container = get_container(request)
    service = container.services["webhook_ingress"]

    receipt = await service.receive(
        provider=provider,
        raw_body=await request.body(),
        headers=request.headers,
        correlation_id=UUID(request.state.correlation_id),
    )
    return AcceptedWebhook(
        receipt_id=receipt.id,
        status=receipt.status,
        duplicate=receipt.status != InboundWebhookStatus.RECEIVED,
    )
```

Keep compatibility aliases if external tools are already configured:

```text
POST /api/v1/webhooks/openproject
POST /api/v1/webhooks/gitlab
```

Both aliases should delegate to the same `WebhookIngressService`; they should
not contain provider parsing.

Recommended HTTP behavior:

| Condition | Response |
|---|---|
| Unknown provider | 404 or 422 |
| Missing/invalid provider authentication | 401 |
| Malformed JSON or envelope | 400 |
| Valid known receipt | 202 with receipt ID |
| Exact duplicate | 200/202 with original receipt ID and `duplicate=true` |
| Supported provider, unsupported action | Persist, return 202, mark unsupported asynchronously |
| Downstream processing failure | Receipt remains retryable; webhook was already acknowledged |

## 11. Worker-side processing service

Suggested module: `brain/application/webhook_processing.py`.

```text
load persisted receipt
    -> select adapter by provider
    -> normalize provider payload
    -> load prior normalized snapshot
    -> diff prior/current snapshot
    -> upsert canonical entity and external mapping
    -> save current snapshot
    -> derive canonical events
    -> append canonical events to durable event log
    -> publish/dispatch events
    -> enqueue workflow commands with TriggerType.EVENT
    -> mark receipt processed
```

A provider adapter should normalize facts; an application service should own
persistence and workflow decisions. For example, the OpenProject adapter can
report the current assignee external ID, but the application state differ should
decide whether that represents a new assignment transition.

## 12. OpenProject webhook adapter

Suggested package:

```text
brain/adapters/webhooks/openproject/
    __init__.py
    adapter.py
    models.py
    envelope.py
    extractors.py
    normalizer.py
    signature.py
    mappings.py
```

Responsibilities:

### `signature.py`

- Read `x-op-signature` case-insensitively.
- Require `sha1=<hex>` for the captured OpenProject contract.
- Calculate HMAC over exact raw bytes.
- Use `hmac.compare_digest`.
- Return generic authentication failure without logging credentials or payload.

If multiple OpenProject versions/algorithms must be supported, make the expected
algorithm an explicit adapter setting; do not silently accept arbitrary
algorithms.

### `envelope.py`

- Require non-empty string `action`.
- Split `<resource>:<operation>` once.
- Select `project`, `work_package`, or `attachment` from the action.
- Require the selected resource to be an object.
- Preserve unknown actions as unsupported receipts rather than converting them
  to a different canonical event.

### `models.py`

Use small Pydantic models with `extra="allow"`. Do not model the complete HAL
schema. Type only fields required by extraction and leave optional embedded/link
sections flexible.

### `extractors.py`

Implement and unit test:

- `extract_raw_text()`;
- `id_from_href()`;
- `collection_elements()`;
- `extract_project()`;
- `extract_project_parent()`;
- `extract_project_ancestors()`;
- `extract_work_package()`;
- `extract_assignee()`;
- `extract_work_package_parent_id()`;
- `extract_work_package_attachments()`;
- `extract_attachment()`;
- `extract_attachment_container()`.

Use precedence:

```text
direct resource field
    -> embedded related resource
    -> relationship link
    -> optional OpenProject API enrichment
```

### `mappings.py`

Keep configurable mappings for provider names to canonical enums:

```yaml
type_mapping:
  Task: task
  Story: story
  Epic: epic
  Bug: bug

status_mapping:
  New: new
  In progress: in_progress
  Closed: done
```

Persist provider ID and name. Never hard-code numeric type, priority, or status
IDs because they are installation-specific.

### `normalizer.py`

Initial action mapping:

```text
project:created       -> PROJECT_CREATED
project:updated       -> PROJECT_CHANGED (new canonical event required)
work_package:created  -> WORK_ITEM_CREATED
work_package:updated  -> WORK_ITEM_CHANGED
attachment:created    -> ATTACHMENT_CREATED (new canonical event required)
```

The current `EventType` enum does not contain `PROJECT_CHANGED` or
`ATTACHMENT_CREATED`; those canonical contracts must be added deliberately with
handlers and tests.

## 13. Relationship to the existing OpenProject adapter

Keep the current responsibilities separate:

```text
OpenProjectHTTPTransport
    -> authenticated REST API calls

OpenProjectAdapter implements WorkManagementPort
    -> fetch/publish/update canonical work items

OpenProjectWebhookAdapter implements WebhookAdapter
    -> authenticate/parse/normalize inbound webhook deliveries
```

They can share:

- extraction helpers;
- external-reference helpers;
- type/status/priority mappings;
- OpenProject REST client for optional enrichment.

They should not be one large adapter because webhook ingress and work-management
commands have different lifecycle and testing requirements.

The existing `_to_work_item()` also needs alignment with the parsing guide: it
currently converts rich description/status dictionaries with `str(...)` rather
than extracting `description.raw` and embedded status/type information.

## 14. Provider replacement example

After the generic boundary exists, adding Jira should require:

```text
JiraWebhookAdapter
    authenticate(raw_body, headers)
    describe(raw_body)
    normalize(raw_body)
```

and composition registration:

```python
registry.register("jira", jira_webhook_adapter)
```

No change should be required in:

- FastAPI webhook route;
- webhook ingress service;
- inbound receipt persistence;
- snapshot differ;
- execution orchestrator;
- planning or verification services.

Only canonical event handlers should matter downstream:

```text
OpenProject work_package:updated --\
Jira issue_updated ---------------> WorkItemChanged / WorkItemAssigned
GitHub issues event --------------/
```

Authentication remains provider-specific behind the same adapter contract:

```text
OpenProject -> HMAC-SHA1 header
GitLab      -> shared token header
Jira        -> configured signature/token mechanism
GitHub      -> HMAC-SHA256 header
```

The application does not contain an `if provider == ...` authentication chain.

## 15. Migration plan

### Phase 0 — Restore and secure the current contract

1. Remove full body/signature/header logging and exception details.
2. Remove `logging.basicConfig()` from the route module.
3. Update tests to the captured `action` + `X-OP-Signature` + HMAC-SHA1 contract.
4. Add sanitized real-payload JSON fixtures.
5. Correct `BRAIN_WORK_MANAGEMENT_*` settings loading so Brain actor mapping works.

### Phase 1 — Introduce generic webhook contracts

1. Add provider-neutral webhook domain models and errors.
2. Add `WebhookAdapter`, registry, and inbound repository ports.
3. Add PostgreSQL inbound receipt and external snapshot adapters/migrations.
4. Add `PROCESS_WEBHOOK` command and handler.
5. Reuse the existing Redis command queue.

### Phase 2 — Extract OpenProject parsing from FastAPI

1. Implement OpenProject signature verifier.
2. Implement envelope parser and resource extractors.
3. Implement project, work-package, and attachment normalizers.
4. Replace route JSON traversal with `WebhookIngressService.receive()`.
5. Preserve the existing OpenProject URL as a compatibility alias.

### Phase 3 — State reconciliation and canonical events

1. Add reverse external-reference lookup.
2. Upsert, rather than blindly create, canonical entities.
3. Store provider snapshots.
4. Diff snapshots to derive assignment/status/hierarchy transitions.
5. Mark workflow commands `TriggerType.EVENT`.
6. Implement echo-loop and duplicate-delivery protection.

### Phase 4 — Extend providers

1. Convert the GitLab webhook route to a `GitLabWebhookAdapter`.
2. Add Jira/XWiki/other adapters only from captured or authoritative payload
   contracts.
3. Run the same provider-neutral contract suite for every adapter.

## 16. Required tests

### OpenProject adapter unit/golden tests

Use sanitized JSON fixtures for:

- root project created;
- subproject created;
- project updated;
- work package created without assignee;
- work package created with embedded attachment;
- work package updated with Brain assignee;
- attachment created with WorkPackage container;
- missing optional `_embedded`;
- null assignee links;
- unknown additional fields;
- malformed action/resource mismatch;
- unknown action;
- invalid signature;
- exact duplicate request.

### State-transition tests

Verify:

- first transition from unassigned to Brain emits `WORK_ITEM_ASSIGNED` once;
- repeated update with the same Brain assignee does not enqueue another run;
- transition away from Brain does not run work;
- status-only updates remain `WORK_ITEM_CHANGED`;
- project and work-item hierarchy remain separate;
- attachments are upserted by provider attachment ID.

### Generic contract tests

Each `WebhookAdapter` must prove:

1. invalid authentication is rejected before parsing side effects;
2. malformed payloads receive a typed error;
3. unknown extra fields do not break known event parsing;
4. output contains no provider-specific `_embedded`, `_links`, or action URLs;
5. external identity includes provider, entity type, and external ID;
6. duplicate delivery does not repeat canonical side effects.

### Runtime integration test

```text
signed HTTP webhook
    -> 202 receipt ID
    -> PostgreSQL inbound receipt committed
    -> Redis ProcessWebhookCommand
    -> worker normalization
    -> canonical entity/mapping/snapshot committed
    -> durable canonical event
    -> one expected workflow command
```

Run API and worker as separate containers to catch uncommitted-session and
in-memory event-bus errors that same-process tests hide.

## 17. Acceptance criteria

The redesign is complete when:

- the API route contains no OpenProject payload traversal;
- provider authentication is selected through a registry, not an `if/elif` chain;
- exact inbound webhook receipts are durable before HTTP acknowledgment;
- project, work-package, and attachment captured payloads normalize correctly;
- unsupported actions are recorded without being misclassified;
- duplicate deliveries are idempotent;
- assignment workflows trigger only on a real transition to the configured Brain
  external actor;
- API and worker can run as separate processes using PostgreSQL and Redis;
- no sensitive webhook payload/header data is logged or returned;
- replacing OpenProject with another adapter does not modify application workflow
  or orchestration code.

## 18. Recommended decision

Do not incrementally add more `body.get(...)` logic to
`brain/api/routes/webhooks.py`. First establish the generic webhook port,
inbound receipt model, and adapter registry. Then implement the captured
OpenProject contract entirely inside an `OpenProjectWebhookAdapter` and move
normalization to worker-side processing.

The durable architectural boundary should be:

> Provider webhook bytes enter through a replaceable adapter; only canonical
> snapshots, external references, and canonical events leave it.
