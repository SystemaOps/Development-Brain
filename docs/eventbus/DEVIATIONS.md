# Event → Command Flow — Deviation Analysis

Reference: `docs/eventbus/event_command_flow.md`

## Documented target flow

```text
Webhook
   ↓
Canonical Event
   ↓
IncomingEventProcessor (dedup, event log, dispatch)
   ↓
EventBus
   ↓
Event Handlers (decide consequences)
   ↓
Command(s), if needed
   ↓
Command Queue
   ↓
Worker → Workflow
```

Rule: **Webhook produces facts. Event handlers decide consequences. Commands
request work. Workers perform the work.**

---

## Deviations

### D1 — The webhook route decides consequences (core deviation)

`brain/api/routes/webhooks.py` decides what should happen instead of an event
handler:

| Decision made in the route | Location |
|---|---|
| `enqueue_command(RUN_WORK_ITEM, ...)` on assignment | `_handle_work_package` (assignment branch) |
| `HumanFeedbackService.receive(...)` on comments | `_normalize_human_comment` |
| `_find_or_create_work_item(...)` persists a work item + mapping | `_handle_work_package` |
| `PullRequestService.handle_merge(...)` on GitLab merge | `gitlab_webhook` |

Per the doc the webhook should only publish the fact:

```python
await incoming_event_processor.process(WorkItemAssigned(...))
```

and a `WorkItemAssignedHandler` should call `enqueue_command(...)`.

### D2 — `IncomingEventProcessor` is never wired

`brain/application/events.py:34` defines the processor (dedup + event log +
dispatch), but `create_brain_container()` (`brain/bootstrap/container.py`)
never instantiates it. Events bypass dedup and the event log entirely.

### D3 — The event bus has zero subscribers in production

`InMemoryEventBus.publish` (`brain/adapters/in_memory/event_bus.py:27`) only
appends to `self.published`. Nothing is subscribed:

- `CanonicalStateProjection` (`brain/application/projections.py:39`) — exists, never subscribed
- `IncrementalRevisionHandler` (`brain/application/revisions.py:37`) — exists, never subscribed
- No `WorkItemAssignedHandler`, `HumanFeedbackReceivedHandler`, `PullRequestMergedHandler`, `RepositoryRevisionChangedHandler` exist at all

Only tests subscribe handlers (`tests/application/test_incremental_revision_handler.py`,
`tests/contracts/event_bus.py`).

### D4 — `WORK_ITEM_ASSIGNED` exists but is never emitted

`EventType.WORK_ITEM_ASSIGNED` is declared (`brain/domain/events.py:27`) and
has a typed model (`WorkItemAssigned`, `brain/domain/event_types.py:88`), but
the webhook publishes `WORK_ITEM_CREATED`/`WORK_ITEM_CHANGED` with a
`changes[]` list embedded in the payload. There is no dedicated
`WorkItemAssigned` event for the handler to react to.

### D5 — Route persists side effects

`_find_or_create_work_item` creates `WorkItem` + `IntegrationMapping` inside
the HTTP route (`brain/api/routes/webhooks.py`). Persistence is a handler/
adapter responsibility, not a webhook responsibility.

### D6 — Comment flow bypasses the event decider

The webhook calls `HumanFeedbackService.receive()` directly. `receive()` only
emits `HUMAN_FEEDBACK_RECEIVED`; the resume logic (`resume_workflow`,
`brain/application/human_feedback.py:67`) is never reached, so a comment on a
waiting work item does not resume the workflow. Per the doc a comment event
should be handled by a handler that stores feedback and enqueues resume.

### D7 — GitLab merge: service mixes publish + enqueue

`PullRequestService.handle_merge` (`brain/application/pull_request_service.py:123`)
publishes `PULL_REQUEST_MERGED` + `REPOSITORY_REVISION_CHANGED` **and** enqueues
`SYNC_REPOSITORY` in the same call (`_enqueue_reingestion`, line 192). The
route calls this service directly. The enqueue decision should live in a
`PullRequestMergedHandler`, not inside the service or the route.

### D8 — Snapshot persistence happens in the route

`_handle_work_package` saves the OpenProject snapshot
(`container.openproject_snapshots.save(...)`) inside the webhook handler. This
is adapter-ish work (provider normalization + snapshot) that belongs behind a
provider adapter, keeping the route fact-only.

### D9 — Semantic changes ride inside a generic payload

The `changes[]` list and full snapshot are embedded in the `WORK_ITEM_*`
envelope `payload` dict. Downstream handlers must re-parse generic dicts
instead of reacting to typed canonical events (`WorkItemAssigned`,
`STATE_CHANGED`, ...). No typed events exist for summary/description/state/
priority/parent changes.

---

## Current actual flow (vs doc)

```text
OpenProject Webhook
   ↓
route (parses, diffs, saves snapshot)          ← D1/D5/D8
   ↓
route publishes WORK_ITEM_CREATED/CHANGED       ← generic payload (D4/D9)
   ↓
InMemoryEventBus → self.published only          ← no processor (D2), no handlers (D3)
   ↓
(dead end)
   ↑
route: enqueue_command(RUN_WORK_ITEM)           ← decided in route (D1)
route: HumanFeedbackService.receive()           ← bypasses decider (D6)
```

GitLab path:

```text
GitLab Webhook
   ↓
route → PullRequestService.handle_merge()        ← decided in route/service (D7)
   ↓
publishes 2 events (dead end) + enqueues SYNC_REPOSITORY directly
```