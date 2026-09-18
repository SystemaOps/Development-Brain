# OpenProject Webhook Parsing — Implementation Plan

Status: Phase A in progress (parser + tests). Phases B–E follow.

## Scope

Update `brain/api/routes/webhooks.py` so OpenProject webhook payloads are
parsed per `docs/webhook/OPENPROJECT_WEBHOOK_PARSING_CONCISE.md` and verified
against the real payloads in `docs/webhook/data.txt`.

## Verified facts from real payloads (data.txt)

All 8 payloads were extracted and inspected:

| Line | action | Key structure |
|---|---|---|
| 2 | `work_package:updated` | wp 43: `_embedded.assignee.id=6`, `_embedded.status.name=New`, `_embedded.priority.name=High`, `_embedded.project.id=8`, `_embedded.type.name=Task`, `description.raw='Description'`, 1 attachment, `_links.activities.href` |
| 14 | `project:created` | project 7, `_links.parent.href=None` |
| 17 | `project:created` | project 8, `_embedded.parent.id=4` (subproject) |
| 20 | `attachment:created` | attachment 3, `_embedded.container.id=43` (WorkPackage) |
| 23 | `project:updated` | project 4, `_embedded.parent.id=3` |
| 26 | `project:updated` | project 4 (description update) |
| 30 | `work_package:created` | wp 43: `_embedded.assignee=None` (contrast with line 2) |
| 33 | `work_package:updated` | wp 40: assignee brain, priority Normal, no attachments |

401 sample confirms the header `x-op-signature: sha1=<hmac-sha1-hex>` — matches
`brain/api/auth.py::verify_webhook` (already implemented).

### Current-code bugs (confirmed by data)

1. `eventType`/`event_type` is read, but real payloads use `action` — always
   falls back to `WORK_ITEM_CHANGED`.
2. `assignee` is read from `work_package.assignee.href`; real path is
   `work_package._embedded.assignee.id` — always `""`, so **assignment
   automation never triggers**.
3. `status` is read from `work_package.status`; real path is
   `work_package._embedded.status.name` — always `""`.
4. `type`, `priority`, `project`, `parent`, `description.raw`, `attachments`,
   `relations`, `activities`, timestamps are not parsed at all.

---

## Phase A — Parser module + fixture-driven tests (in progress)

### A1. New module: `brain/application/openproject_parser.py`

Pure functions, no I/O, no orchestrator imports.

- `parse_action(body) -> str` — reads `action`, falls back to `eventType` /
  `event_type` (backward compat with existing tests).
- `id_from_href(href) -> int | None` — doc §7.
- `OpenProjectWorkItemSnapshot` dataclass:
  `external_id, summary, description, type, priority, state, closed,
  project_id, project_name, assignee_id, assignee_name, parent_id,
  attachments, relations, activities_url, created_at, updated_at`
- `parse_work_item(body) -> OpenProjectWorkItemSnapshot | None` — doc §2/§16.
- `parse_project(body) -> dict` — id, name, parent_id (`_embedded.parent.id`).
- `parse_attachment(body) -> dict` — id, fileName, contentType, fileSize,
  download_url, container work item id.
- `diff_snapshots(previous, current) -> list[SemanticChange]` — doc §14:
  `SUMMARY_CHANGED, DESCRIPTION_CHANGED, ASSIGNEE_CHANGED, STATE_CHANGED,
  PRIORITY_CHANGED, PARENT_CHANGED`.

### A2. Test fixtures from real data

Extract the 8 payloads from `docs/webhook/data.txt` into
`tests/fixtures/openproject/*.json` (checked-in copies of the real bodies).

### A3. New test file: `tests/test_phase34_webhook_parsing.py`

Fixture-driven assertions:

- `parse_work_item` on wp 43 updated: all 15 fields exact.
- `parse_work_item` on wp 43 created: `assignee_id=None`; diff vs updated →
  `ASSIGNEE_CHANGED`.
- `id_from_href`: `/api/v3/work_packages/20` → `20`, `None` → `None`.
- `parse_project` on lines 14/17/23: parent via `_embedded.parent.id`.
- `parse_attachment` on line 20: `container.id=43`.
- `diff_snapshots`: each semantic event for its field change.
- `parse_action` backward compat.

---

## Phase B — Route refactor (`brain/api/routes/webhooks.py`)

```
POST /api/v1/webhooks/openproject
  ├─ verify_webhook("openproject")            (unchanged)
  ├─ action = parse_action(body)
  ├─ work_package:* → snapshot = parse_work_item(body)
  │    previous = snapshot_store.get(id); changes = diff(previous, snapshot)
  │    store.save(snapshot)
  │    publish envelope {snapshot, changes}
  │    assignment: only on created or ASSIGNEE_CHANGED with assignee==brain
  │                → enqueue RUN_WORK_ITEM
  ├─ project:* → parse_project → publish PROJECT_CHANGED, upsert + parent edge
  └─ attachment:created → parse_attachment → publish ATTACHMENT_CREATED
```

## Phase C — Snapshot store

`brain/ports/openproject_snapshot.py` + in-memory adapter wired into
`BrainContainer` as `services["openproject_snapshots"]`.

## Phase D — Route-level tests (ASGI, signed)

- created+assigned → `triggered=assignment`
- updated without assignee change → no command
- updated with assignee→brain → `triggered=assignment`
- project:created / attachment:created → accepted + event published
- existing 6 tests updated to `action` field

## Phase E — Verification

`ruff`, `mypy`, full `pytest`, parser round-trip over all 8 fixtures.