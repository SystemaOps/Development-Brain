# Event → Command Flow — Remediation Plan

Reference: `docs/eventbus/event_command_flow.md`
Deviation analysis: `docs/eventbus/DEVIATIONS.md`

Goal: restore the documented separation — **webhook produces facts, event
handlers decide consequences, commands request work, workers perform it.**

---

## Phase 1 — Wire the ingestion chain (fixes D2, D3) ✅ implemented

### 1.1 Instantiate `IncomingEventProcessor` in the composition root
- `brain/bootstrap/container.py::create_brain_container`
- Needs: `services["events"]` (bus), an `IdempotencyStore`, an `EventLogRepository`
- In-memory adapters for both if none exist; expose
  `container.incoming_events: IncomingEventProcessor`
- `IncomingEventProcessor.process()` already does dedup → dispatch → event log
  (`brain/application/events.py:45`)

Status: done — uses `repositories.idempotency` (PostgresIdempotencyStore) and
`repositories.event_log` (PostgresEventLogRepository), both already wired in
`PostgresRepositories`; exposed as `container.incoming_events`.

### 1.2 Wire event handlers as subscribers
- New `brain/application/event_handlers.py` with handlers (below)
- `create_brain_container` subscribes each handler to its `EventType` on the
  bus, e.g. `await events.subscribe(EventType.WORK_ITEM_ASSIGNED.value, handler)`
- Subscribe `CanonicalStateProjection` and `IncrementalRevisionHandler` too —
  they exist but were never wired

Status: done for existing handlers — `CanonicalStateProjection` subscribed to
WORK_ITEM_CREATED/WORK_ITEM_CHANGED/PROJECT_CREATED/PROJECT_CHANGED/
REPOSITORY_REGISTERED/REQUIREMENT_CHANGED/DOCUMENT_CHANGED/EXECUTION_*;
`IncrementalRevisionHandler` subscribed to REPOSITORY_REVISION_CHANGED only
when a source-control port exists (Milestone 1 returns None). New consequence
handlers (WorkItemAssignedHandler, ...) come in Phase 3.

---

## Phase 2 — Typed events for provider facts (fixes D4, D9) ✅ implemented

### 2.1 Emit typed canonical events instead of generic payloads
The webhook must publish facts the bus understands. Options:

| Fact | Event |
|---|---|
| Work package created | `WORK_ITEM_CREATED` (exists) |
| Work package assigned to brain | `WORK_ITEM_ASSIGNED` (exists, never emitted) |
| Human comment | `HUMAN_FEEDBACK_RECEIVED` (exists, emitted by service) |
| Attachment added | `ATTACHMENT_CREATED` (added in parsing work) |
| Project created/updated | `PROJECT_CHANGED` (added in parsing work) |
| State/summary/priority/parent changed | new semantic events (TBD, optional) |

- The parser (`brain/application/openproject_parser.py`) already computes
  `changes[]`; convert each to an emitted event or fold into
  `WORK_ITEM_CHANGED` payload (documented decision below)

Status: done — the webhook now emits typed `WorkItemCreated` / `WorkItemChanged`
envelopes via `model_to_envelope` when a canonical work item is resolvable
(`work_package:created` -> `WorkItemCreated`, else `WorkItemChanged`); the
semantic `changes[]` list and the provider snapshot ride along in the payload
(documented decision: fold into the event payload for now).  When no canonical
project exists the route falls back to the generic envelope, so a missing
project never breaks the webhook.

### 2.2 Dedicated `WorkItemAssigned` emission
- When `ASSIGNEE_CHANGED` and assignee == brain actor, publish
  `WorkItemAssigned(...)` (typed model exists at
  `brain/domain/event_types.py:88`)

Status: done — the assignment branch now additionally publishes a typed
`WorkItemAssigned` event (`work_item_id` + `external_actor_id` = the OpenProject
user id, since provider user ids are not canonical ActorId UUIDs).  The typed
model was extended with `external_actor_id` / optional `actor_id` to carry
provider-side identities without fabricating canonical ids.

---

## Phase 3 — Event handlers decide consequences (fixes D1, D5, D6, D7)

New `brain/application/event_handlers.py`:

```python
class WorkItemAssignedHandler(EventHandler):
    async def handle(self, event):            # WorkItemAssigned
        # resolve/create work item if needed (moved from route)
        await enqueue_command(RUN_WORK_ITEM, work_item_id=event.work_item_id)

class HumanFeedbackReceivedHandler(EventHandler):
    async def handle(self, event):            # HumanFeedbackReceived
        await feedback_service.resume_workflow(feedback)   # store + resume

class PullRequestMergedHandler(EventHandler):
    async def handle(self, event):            # PullRequestMerged
        # publish RepositoryRevisionChanged
        await enqueue_command(SYNC_REPOSITORY, external_ref=...)

class RepositoryRevisionChangedHandler(EventHandler):
    async def handle(self, event):
        await revision_handler.handle(event)  # reuse IncrementalRevisionHandler
```

### 3.1 Strip decision logic from the routes
`brain/api/routes/webhooks.py` becomes fact-only:

```python
@router.post("/api/v1/webhooks/openproject")
async def openproject_webhook(...):
    container: BrainContainer = get_container(request)
    body = await request.json()
    await container.incoming_events.process(parse_to_event(body))
    return {"accepted": True, ...}
```

- Remove `enqueue_command` calls from `_handle_work_package`
- Remove `_normalize_human_comment` direct service call
- Remove `_find_or_create_work_item` persistence (move into handler)
- GitLab route: publish `PULL_REQUEST_MERGED` fact; `PullRequestMergedHandler`
  calls `handle_merge` consequences

---

## Phase 4 — Tests

- `tests/test_phase34_webhook_route.py`: webhook now asserts events published
  and `command_id` absent from route response (command enqueued by handler)
- New `tests/test_event_handlers.py`:
  - `WorkItemAssignedHandler` enqueues `RUN_WORK_ITEM`
  - `HumanFeedbackReceivedHandler` resumes workflow
  - `PullRequestMergedHandler` enqueues re-ingestion
  - dedup: same idempotency key processed once
  - event log appended per processed event
- Existing suite stays green (route tests updated for the fact-only contract)

---

## Phase 5 — Verification

- `ruff`, `mypy`, full `pytest`
- Manual POST of `docs/webhook/data.txt` payloads → assert typed events on bus,
  commands enqueued by handlers (not by route)

---

## Open decisions

1. **Semantic change events**: emit one typed event per `changes[]` item
   (`STATE_CHANGED`, ...) or keep them in the `WORK_ITEM_CHANGED` payload?
   Recommended: fold into `WORK_ITEM_CHANGED` payload for now; add typed events
   only when a handler needs one.
2. **Snapshot save**: keep in route (adapter behavior) or move behind the
   provider adapter? Recommended: keep in route for now — it is normalization,
   not a consequence decision.
3. **Idempotency/event-log adapters**: in-memory for now; PostgreSQL later.

## Dependencies / risks

- `IncomingEventProcessor` needs an `IdempotencyStore` + `EventLogRepository`;
  check `brain/ports/idempotency.py` and `brain/ports/event_log.py` for
  existing adapters before creating new ones
- Moving `_find_or_create_work_item` into a handler requires the handler to
  reach repositories — handlers will receive the container (same pattern as
  `PullRequestService`)