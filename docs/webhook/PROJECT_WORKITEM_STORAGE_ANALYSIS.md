# Project & WorkItem Storage/Retrieval — Hierarchy Analysis

Scope: how `Project` and `WorkItem` are persisted, retrieved, and whether a
project/work-item hierarchy is maintained anywhere — and why
`_work_item_id_for_external` falls back to a brute-force loop.

---

## 1. Storage (PostgreSQL)

### `projects` (`brain/adapters/postgresql/tables.py:43`)

| Column | Notes |
|---|---|
| `id` (UUID, PK) | canonical project id |
| `name`, `status`, `description` | attributes |
| `external_refs` | **JSONB column** — `_replace_external_refs` also writes rows into `external_references` (owner_type=`project`) |

**No `parent_id` column** — project→project hierarchy (doc §12
`(Project)-[:PARENT_OF]->(Project)`) is **not stored relationally**.

### `work_items` (`tables.py:77`)

| Column | Index | Notes |
|---|---|---|
| `id` (UUID, PK) | — | canonical work item id |
| `project_id` (UUID) | `ix_work_items_project_id` | flat `project_id` FK — **not a parent reference** |
| `parent_id` (UUID, nullable) | `ix_work_items_parent_id` | **self-referential hierarchy** — work item → work item parent |
| `title`, `type`, `status…` | — | attributes |
| `external_refs` (JSONB) | — | mirrored into `external_references` (owner_type=`work_item`) |

### `external_references` (`tables.py:256`) — the provider identity bridge

| Column | Index |
|---|---|
| `owner_type` (`project`/`work_item`/`repository`/…) | `ix_external_references_owner (owner_type, owner_id)` |
| `owner_id` (UUID) | |
| `provider` (`openproject`, `gitlab`, …) | **`ix_external_references_provider_external (provider, external_id)`** |
| `external_id` | |

**This index exists** — a direct indexed query
`WHERE provider='openproject' AND external_id='43' AND owner_type='work_item'`
would resolve an external work package to a canonical `WorkItem` in O(1).

### `work_management_mappings` (`tables.py:610`) — the integration mapping

| Column | Constraint |
|---|---|
| `work_item_id` | `UNIQUE (work_item_id, provider)` |
| `provider`, `external_id`, `sync_state` | — |

**No index on `(provider, external_id)`** and no repository method to look up
by external id (`get_mapping` is keyed by `work_item_id + provider`,
`repositories.py`). The mapping table therefore cannot serve the reverse
lookup the webhook needs.

---

## 2. Retrieval — the current state

| Query | Method | Implementation |
|---|---|---|
| Work items of a project | `WorkItemRepository.list_by_project(project_id)` | indexed `WHERE project_id = ?` ✅ |
| Children of a work item | `WorkItemRepository.list_by_work_item(parent_id)` | indexed `WHERE parent_id = ?` ✅ **but never called in production** (grep: only defined, zero callers) |
| External → canonical work item | **none** ❌ | `_work_item_id_for_external` brute-force loop |
| External → any owner | **none** ❌ | `external_references` index unused by repositories |

### Why `_work_item_id_for_external` loops

```python
for project in await container.repositories.projects.list():          # all projects
    for work_item in await container.repositories.work_items.list_by_project(project.id):
        for ref in work_item.external_refs:                            # JSONB refs in memory
            if ref.provider == "openproject" and ref.external_id == external_id:
                return work_item.id
```

- No repository API exposes "work item by provider external id".
- The `external_references` table has the perfect index but no query method
  (`_replace_external_refs` only writes/deletes; nothing reads by
  provider+external_id).
- The mapping table (`work_management_mappings`) is written by
  `_find_or_create_work_item` but has no reverse lookup either.
- Cost: `O(projects × work_items)` in-process scans on every webhook —
  harmless at reference scale, a live problem at production scale.

---

## 3. Hierarchy — where is it (not) maintained?

### WorkItem.parent_id (relational, indexed, unused)
- Stored: `WorkItemRow.parent_id` + `ix_work_items_parent_id` ✅
- `list_by_work_item(parent_id)` implemented (Postgres + in-memory) ✅
- **Never called** by any service/handler ❌
- **Never populated by the OpenProject flow**: the webhook parser extracts
  `parent_id` from `_links.parent.href` (doc §7), but
  `_find_or_create_work_item` constructs `WorkItem(...)` **without
  `parent_id`** — the parsed parent id only rides in the event payload
  (`webhooks.py:364`), never onto the canonical row.

### Project hierarchy (missing)
- No `projects.parent_id`, no `(Project)-[:PARENT_OF]->(Project)` anywhere.
- `parse_project` extracts `_embedded.parent.id` and publishes it in the
  `PROJECT_CHANGED` payload (`webhooks.py:186`), but nothing persists it.

### Knowledge graph (Neo4j) — partial
`GraphProjectionService` (`brain/application/graph_projection.py:142`):
- `(WorkItem)-[:PART_OF]->(Project)` ✅
- `(WorkItem)-[:IMPLEMENTS]->(Requirement)` ✅
- **`(WorkItem)-[:PARENT_OF]->(WorkItem)` ❌ absent** — the loop over
  `work_items.list_by_project` never emits a parent relation (no
  `RelationType.PARENT_OF` exists in `brain/domain/graph_schema.py`).
- Requirement hierarchy partially covered via `DERIVED_FROM` for
  `requirement.parent_id` — the work-item equivalent does not exist.

---

## 4. Gap summary

| Capability | Expected (doc) | Actual |
|---|---|---|
| External id → work item | O(1) via `external_references` index or mapping table | ❌ brute-force in-process loop |
| Work item children | `list_by_work_item(parent_id)` | ⚠️ implemented, never called |
| Work item parent persisted | `WorkItem.parent_id` on every create | ❌ never populated by webhook |
| Project hierarchy | `(Project)-[:PARENT_OF]->(Project)` | ❌ not stored anywhere |
| Graph work-item hierarchy | `(WorkItem)-[:PARENT_OF]->(WorkItem)` | ❌ missing relation + no `PARENT_OF` vocabulary |
| Graph project containment | `(Project)-[:CONTAINS]->(WorkItem)` | ⚠️ expressed as `PART_OF` (work_item→project) |

---

## 5. Recommended fixes (ranked)

1. **Add a repository query** `find_by_external(provider, external_id,
   owner_type)` on `external_references` (index exists) and use it in
   `_work_item_id_for_external` — removes the loop.
2. **Populate `WorkItem.parent_id`** in `_find_or_create_work_item` from
   `snapshot.parent_id` (resolve parent's canonical id via fix #1).
3. **Add `RelationType.PARENT_OF`** + emit parent relations in
   `GraphProjectionService` for both work items and projects.
4. **Add `projects.parent_id`** (or a `project_relations` table) so
   `PROJECT_CHANGED` parent payloads persist.
5. Optionally index `work_management_mappings (provider, external_id)` and
   reuse the mapping table as the reverse-lookup source of truth (Task 14.4).