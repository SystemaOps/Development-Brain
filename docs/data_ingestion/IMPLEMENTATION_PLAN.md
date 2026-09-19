# Implementation Plan — OpenProject Bootstrap + Pull Reconciliation

> Companion to `OPENPROJECT_EXISTING_PROJECT_BOOTSTRAP_PLAN.md`. One combined
> plan: initial bootstrap onboarding of an existing OpenProject project, then
> durable sync state and periodic pull reconciliation.

## Decisions

- Scope is combined: bootstrap first, then pull reconciliation as the
  "after onboarding" phase.
- New canonical `Comment` and `Attachment` entities (PostgreSQL tables + graph
  labels); comments/attachments are not folded into existing models.
- `Project.parent_id` is added to the canonical model; project hierarchy is
  persisted (`(Project)-[:PARENT_OF]->(Project)`).
- OpenProject type/status names map strictly to canonical
  `WorkItemType`/`HumanWorkStatus` with fallback (`unknown -> task`,
  `unknown -> new`); raw provider names are preserved in `external_refs`.
- Work-package relations persist in a canonical `work_item_relations` table
  and as graph edges (new `RelationType` members).
- Attachments: metadata + download links in milestone 1; Markdown/text
  content parsed; PDF content deferred until Docling is enabled.
- Webhooks arriving during bootstrap are processed idempotently (durable
  snapshots make double-processing a no-op).

---

## Phase 0 — Domain & Persistence Foundations

| Task | Detail | Files |
|---|---|---|
| 0.1 | New canonical entities: `Comment` (id, work_item_id, author ref, text, created_at, external_refs), `Attachment` (id, work_item_id, file_name, content_type, file_size, download_url, external_refs, ingested_content). Domain models + PostgreSQL tables + in-memory/Postgres repos. | `brain/domain/comments.py`, `brain/domain/attachments.py`, `adapters/postgresql/tables.py`, `repositories.py`, `database.py`, `adapters/in_memory/` |
| 0.2 | `Project.parent_id: ProjectId \| None` + table migration + `(Project)-[:PARENT_OF]->(Project)` | `brain/domain/projects.py`, `tables.py`, Alembic migration |
| 0.3 | `work_item_relations` table (source_work_item_id, target_work_item_id, relation_type, external_ref) + repo | `tables.py`, `domain/work_item_relations.py` |
| 0.4 | Extend graph vocabulary: `GraphLabel.COMMENT`, `GraphLabel.ATTACHMENT`; `RelationType.PARENT_OF`, `BLOCKS`, `RELATES_TO`, `PRECEDES`, `FOLLOWS`, `HAS_ATTACHMENT`, `HAS_COMMENT`, `COMMENT_ON`, `AUTHORED` | `brain/domain/graph_schema.py` |
| 0.5 | Durable snapshot store: replace `InMemoryOpenProjectSnapshotStore` with Postgres-backed `OpenProjectWorkItemSnapshot` table (external_id, snapshot JSON, updated_at, ingested_at) | `adapters/postgresql/`, `bootstrap/providers.py` |
| 0.6 | `ProviderSyncWatermark` (provider, sync_key, last_synced_at, last_external_id) + port + in-memory/Postgres repos | `domain/sync_watermark.py`, `ports/sync_watermark.py` |
| 0.7 | `ProviderBootstrapState` (project_id, provider, status CONNECTED..LIVE_SYNC, stage, last_page, items_processed, last_error, started/completed_at) for checkpoint/resume | new table + repo |
| 0.8 | Type/status mapping module: OP type name -> `WorkItemType`, OP status name -> `HumanWorkStatus`; unknown -> fallback; raw names preserved | `application/openproject_mapping.py` |
| 0.9 | Efficient external-ref reverse lookup `(provider, external_type, external_id) -> canonical id` (replaces O(n) scan in `webhooks.py`) | `ports/repositories.py` / work-item repository |

**Gate:** Postgres-backed tests prove snapshots/watermark/bootstrap state
survive container restart; `Project.parent_id` and relations persist.

---

## Phase 1 — Unified Ingestion Service

| Task | Detail | Files |
|---|---|---|
| 1.1 | Extract `_find_or_create_work_item` (webhook route) into a shared service using the reverse lookup (0.9) | `brain/application/openproject_ingestion.py` (new) |
| 1.2 | `ingest_work_item_snapshot(snapshot, mode="BOOTSTRAP"\|"LIVE", source=...)`: identity resolution, WorkItem persistence, parent/relation resolution, attachment reconciliation, snapshot persistence, graph update. LIVE diffs vs durable snapshot -> `SemanticChange[]` -> canonical events. BOOTSTRAP persists + builds graph + baseline, emits no workflow triggers | new service |
| 1.3 | Two-pass relationship resolution: pass 1 create entities, pass 2 resolve parent + relations via reverse lookup; persist `work_item_relations` + graph edges | service + relations repo |
| 1.4 | Attachment reconciliation: metadata + download URL persisted; Markdown/text downloaded -> `DocumentIngestionService`; PDFs metadata-only until Docling enabled | service + `DocumentConversionPort` |
| 1.5 | Comments: fetch `/work_packages/{id}/activities`; BOOTSTRAP -> context only; LIVE new comments -> `HumanFeedbackReceived` | service |
| 1.6 | Graph projection of the work-item subgraph (project tree, PART_OF, PARENT_OF, BLOCKS, RELATES_TO, ASSIGNED_TO, HAS_COMMENT, HAS_ATTACHMENT) using provider identity | `application/graph_projection.py` extension |
| 1.7 | Refactor webhook route to call the shared service (`mode=LIVE, source=webhook`); idempotent during bootstrap | `api/routes/webhooks.py` |

**Gate:** webhook and bootstrap paths produce identical canonical state for
the same snapshot; historical assignment/comments produce zero workflow events.

---

## Phase 2 — Bootstrap Command & Service

| Task | Detail | Files |
|---|---|---|
| 2.1 | `BOOTSTRAP_PROJECT` command: `CommandType` + model + handler registration; API/CLI -> queue -> worker | `brain/domain/commands.py`, `application/command_handlers.py` |
| 2.2 | `OpenProjectProjectBootstrapService` (`brain/application/openproject_bootstrap.py`): discover project + hierarchy -> fetch all work packages (pagination) -> unified ingestion -> comments -> attachments -> graph -> durable baseline -> watermark -> READY | new service |
| 2.3 | Transport additions: `list_projects()`, `list_work_packages(project_id, offset, page_size)`, `get_activities(id)`, attachment download | `adapters/work_management/openproject_http.py` |
| 2.4 | Entry points: `POST /api/v1/projects/{id}/bootstrap` (202), `brainctl project bootstrap`, reconcile trigger | `api/routes/projects.py`, `cli/commands/projects.py` |
| 2.5 | Failure/resume: bootstrap state drives resume-from-checkpoint or idempotent restart | service + state repo |

**Gate:** fake-transport test imports 1 project + 2 subprojects + 100 work
items with no duplicates, correct hierarchy, and no `WorkItemAssigned` /
`RUN_WORK_ITEM` for a pre-assigned Brain task.

---

## Phase 3 — Pull Reconciliation

| Task | Detail | Files |
|---|---|---|
| 3.1 | `WorkManagementPullSyncService` (extend `work_management_sync.py`): watermark -> paginated `list_updated_work_packages` -> unified ingestion (LIVE/pull) -> advance watermark after batch; missed-package sweep for previously-mapped IDs | `brain/application/work_management_sync.py` |
| 3.2 | Scheduler: implement `reconcile_work_management`; fix queue wiring in `scheduler/main.py` (currently no queue -> `_enqueue_sync` no-ops); add `jobs.run_work_management_reconciliation` | `scheduler/reconciliation.py`, `scheduler/main.py`, `scheduler/jobs.py` |
| 3.3 | Settings: `sync_enabled`, `sync_interval_seconds`, `sync_since_days`, `page_size` on `WorkManagementSettings` | `bootstrap/settings.py` |
| 3.4 | First pull after bootstrap starts at `watermark - 5s` overlap; unchanged snapshots diff to no-op | pull service |
| 3.5 | Manual triggers: `POST /api/v1/work-management/sync` (202), `brainctl work-item sync` | `api/routes/`, `cli/commands/work_items.py` |

**Gate:** scheduler test proves a provider change (no webhook) is pulled,
diffed, and converted to canonical events exactly once; overlap pull does not
duplicate.

---

## Phase 4 — Tests & Verification

- Contract tests for watermark / bootstrap-state / snapshot repos
  (in-memory + Postgres, `tests/contracts/` convention).
- `tests/application/test_openproject_bootstrap.py`: scale import, hierarchy
  two-pass, historical assignment/comments (no events), attachment idempotency,
  change-during-bootstrap + overlap pull (processed once), restart survival.
- `tests/application/test_work_management_pull_sync.py`: missed-webhook
  recovery, no duplicates, conflict rows, assignment -> `RUN_WORK_ITEM`.
- Type/status mapping unit tests; webhook-during-bootstrap idempotency test.
- Scheduler integration test (`test_phase29_scheduler.py` pattern).
- Verification chain: `uv run ruff format tests brain` ->
  `uv run ruff check tests brain` -> `uv run mypy brain` ->
  `uv run pytest -q`.

**Migrations:** one Alembic migration per cluster — (a) `Project.parent_id` +
`work_item_relations`, (b) `comments` + `attachments`, (c) snapshots,
(d) watermark + bootstrap state.

**Order:** 0 -> 1 -> 2 -> 3 -> 4. GitLab/XWiki pull remain separate
follow-ups.