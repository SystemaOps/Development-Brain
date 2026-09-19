# `_find_or_create_work_item` — Implementation Analysis

File: `brain/api/routes/webhooks.py:373-412`

## Signature

```python
async def _find_or_create_work_item(
    container: BrainContainer,
    snapshot: OpenProjectWorkItemSnapshot,
) -> WorkItem | None:
```

| Input | Type | Meaning |
|---|---|---|
| `container` | `BrainContainer` | Composition root — repositories, settings, services |
| `snapshot` | `OpenProjectWorkItemSnapshot` | Normalized work package (parser output, `brain/application/openproject_parser.py`) |

| Output | Meaning |
|---|---|
| `WorkItem` | The canonical (internal) work item for the external package |
| `None` | No canonical project exists yet (no repository project to attach to) |

## Purpose

Resolve the **canonical Brain work item** that corresponds to an external
OpenProject work package (`external_id`), creating it on first sight. It is
the bridge between the provider-side identity ("OpenProject wp 43") and the
internal identity (`WorkItemId` UUID).

It is called once per work-package webhook in `_handle_work_package`
(`webhooks.py:93`) **before** the typed `WorkItemCreated`/`WorkItemChanged`
envelope is published, so the typed event always carries a canonical work
item.

## Behavior — step by step

### 1. Idempotent lookup (lines 383-387)

```python
existing_id = await _work_item_id_for_external(container, snapshot.external_id)
if existing_id is not None:
    existing = await container.repositories.work_items.get(existing_id)
    if existing is not None:
        return existing
```

- Searches for an existing canonical work item whose `external_refs` contains
  `provider == "openproject"` and `external_id == snapshot.external_id`
  (helper `_work_item_id_for_external`, `webhooks.py:330`).
- **This is the key idempotency guard**: repeated webhook deliveries (OpenProject
  retries, duplicate events) return the *same* canonical work item instead of
  creating a duplicate on every delivery. This fixed a latent duplicate-work-item
  bug (previously every webhook created a fresh `WorkItem` with a new UUID).

### 2. Project resolution (lines 389-394)

```python
project = None
for candidate in await container.repositories.projects.list():
    project = candidate
    break
if project is None:
    return None
```

- Picks the **first** canonical project from the repository.
- If **no project exists** → returns `None`; the caller falls back to the
  generic (non-typed) envelope so the webhook is never broken by a missing
  project.
- **Known simplification**: the OpenProject `snapshot.project_id` (external id,
  e.g. `"8"`) is *not* used to select the canonical project — there is no
  external-project → canonical-project mapping yet. The first project is a
  placeholder policy until project reconciliation (Phase 36) is wired for
  OpenProject.

### 3. Work item construction (lines 396-406)

```python
ref = ExternalReference(
    provider="openproject",
    external_id=snapshot.external_id,
    external_type="work_package",
)
work_item = WorkItem(
    project_id=project.id,
    title=str(snapshot.summary or f"OpenProject {snapshot.external_id}"),
    description=snapshot.description,
    external_refs=[ref],
)
```

| `WorkItem` field | Source | Fallback |
|---|---|---|
| `project_id` | first canonical project | — |
| `title` | `snapshot.summary` (subject) | `"OpenProject {external_id}"` |
| `description` | `snapshot.description` (raw markdown) | `""` |
| `external_refs` | one `ExternalReference` (provider `openproject`) | — |

Note: priority/state/assignee are **not** projected onto the canonical work
item at creation time — they live in the snapshot payload on the event bus and
are consumed by projections/handlers.

### 4. Persistence + mapping (lines 407-412)

```python
created = await container.repositories.work_items.create(work_item)
mapping = IntegrationMapping(
    work_item_id=created.id, provider="openproject", external_id=snapshot.external_id
)
await container.repositories.work_management_integrations.save_mapping(mapping)
return created
```

- `work_items.create` persists the canonical work item (PostgreSQL).
- `save_mapping` writes the **`IntegrationMapping`** row
  (`brain/domain/work_management.py`: `work_item_id` ↔ `provider` ↔
  `external_id`, `sync_state = PENDING`) through
  `WorkManagementIntegrationRepository`
  (`brain/ports/work_management_repo.py:17`). This is the durable
  internal↔external linkage (Task 14.4) that survives provider swaps.

## Call graph

```
openproject_webhook (POST /api/v1/webhooks/openproject)
  └─ _handle_work_package
       ├─ parse_work_item(body) ──→ snapshot
       ├─ _find_or_create_work_item(container, snapshot)   ← this function
       │    ├─ _work_item_id_for_external(...)             lookup by external ref
       │    ├─ repositories.projects.list()                first project
       │    ├─ repositories.work_items.create(...)         persist canonical
       │    └─ repositories.work_management_integrations.save_mapping(...)
       └─ model_to_envelope(WorkItemCreated|WorkItemChanged(work_item=...))
            └─ event_bus.publish(envelope)
```

## Dependencies

| Dependency | Purpose |
|---|---|
| `_work_item_id_for_external` (`webhooks.py:330`) | external-ref → canonical id lookup |
| `container.repositories.projects` | canonical project list |
| `container.repositories.work_items` | canonical work item create/get |
| `container.repositories.work_management_integrations` | `IntegrationMapping` persistence |
| `OpenProjectWorkItemSnapshot` | normalized snapshot (parser) |
| `ExternalReference`, `WorkItem`, `IntegrationMapping` | domain models |

## Edge cases

| Case | Behavior |
|---|---|
| Work package delivered twice | Returns the existing canonical work item (no duplicate) |
| No canonical project exists | Returns `None`; caller publishes the generic envelope |
| Empty `summary` | Title falls back to `"OpenProject {external_id}"` |
| Snapshot has no `external_id` | `parse_work_item` returns `None` earlier — never reaches here |
| Comment-only webhook | `_find_or_create_work_item` still runs first (creates the mapping), then the comment normalizes with a resolvable `work_item_id` |

## Known limitations / future work

1. **First-project policy**: canonical project is not derived from
   `snapshot.project_id`; needs an external→canonical project mapping.
2. **No field projection**: priority/state/assignee are not written onto the
   canonical `WorkItem`; only the bus payload carries them.
3. **Placement**: currently lives in the route module; per
   `docs/eventbus/event_command_flow.md` it is adapter-ish work (provider →
   canonical resolution) and could move behind a service/handler so the webhook
   layer stays purely fact-producing.