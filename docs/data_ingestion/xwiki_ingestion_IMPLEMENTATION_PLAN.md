# Implementation Plan — XWiki Data Ingestion Runtime Fix

> Companion to `docs/data_ingestion/xwiki_ingestion_fix_plan.md`. Converts that
> requirements document into a concrete, ordered implementation plan for this
> repository.

## Design decisions (resolved here)

| Decision | Choice | Rationale |
|---|---|---|
| Content format | Dedicated **XWikiSyntaxParser**; `mime_type="text/x-xwiki"` | Verified: XWiki REST `<content>` returns raw `xwiki/2.1` syntax even with `?media=converted`; the render endpoint requires a CSRF form token (403 for non-browser clients). No server-side HTML conversion is reliably available. |
| Watermark | Reuse `ProviderSyncWatermark` (existing `SyncWatermarkRepository`) | No new persistence model. Key: `provider="xwiki"`, `sync_key="project:<project_uuid>:space:<space>"`. |
| Project mapping | Page → space → canonical project via `ExternalReference(xwiki, space, <space>)` | Project-space relationships live in canonical data (doc §18), not static config. |
| Runtime trigger | `reconcile_documentation` in the scheduler (inline, per-cycle) | Matches the doc's orchestration-only requirement; per-page error isolation so one bad page never aborts the cycle. |
| `DocumentationCatalogSyncService` | Keep as discovery/catalog-only; its `ingest_document` delegates to `DocumentIngestionService` | Avoids a second partial ingestion path (doc §8). |
| `XWikiMappingService` | Used for `ref()`/space extraction; `to_source_artifact` replaced by adapter's fetch path | One mapping source, no duplication (doc §9). |

---

## Step 1 — Register runtime document parsers

`brain/bootstrap/providers.py` (`build_services`, `DocumentIngestionService` construction):

```python
registry = DefaultParserRegistry()
registry.register(AdrParser(MarkdownParser()))
registry.register(MarkdownParser())
registry.register(HtmlParser())
registry.register(PdfParser())
registry.register(XWikiSyntaxParser())   # Step 2
ingestion = DocumentIngestionService(..., parser_registry=registry, ...)
```

- `AdrParser` wraps `MarkdownParser` (register first, selection policy is first-match).
- **Acceptance:** `build_services(...)` registry contains the parsers; the runtime `INGEST_DOCUMENT` command no longer fails with "no parser registered".
- **Test:** construction-level test asserting registry contents (doc §16).

## Step 2 — XWiki content format + `XWikiSyntaxParser`

New file `brain/adapters/parsers/xwiki_syntax.py`:

- Implements `DocumentParser`; `can_parse` matches `mime_type == "text/x-xwiki"` or the `xwiki/2.1` syntax metadata.
- Converts the MVP subset of XWiki 2.x syntax into `ParsedDocument` nodes:
  - headings `= h1 =` … `====== h6 =======` → heading path / nodes
  - bold `**x**`, italic `//x//`, underlined `__x__`, monospace `##x##`
  - bullet `*` / numbered `#` lists, definition lists
  - links `[[page]]`, `[[label|page]]` → `links`
  - code blocks `{{code language="py"}}…{{/code}}` → content node
  - macros `{{...}}` stripped (no expansion in MVP)
  - tables `| a | b |` captured as a table node
- Adapter marks content correctly: `XWikiDocumentationAdapter.fetch_document` sets
  `mime_type="text/x-xwiki"` and records `syntax` + `modified` in metadata.
- **Acceptance (doc §16):** a real `Main.WebHome` payload parses into a meaningful structure
  (title, headings, paragraphs) and round-trips through `DocumentIngestionService`.

## Step 3 — XWiki space → Brain project mapping

New module `brain/application/xwiki_ingestion.py` with a resolver:

```python
async def resolve_project_for_page(ref, *, projects) -> Project | None:
    space = extract_space(ref.external_id)          # "ADAS.Requirements.Braking" -> "ADAS"
    # find project whose external_refs contain (xwiki, space, space)
```

- Uses `ProjectRepository.find_by_external_ref("xwiki", space, "space")` (already implemented).
- Unmapped page → `UnmappedXWikiSource` result: logged, counted as failed, **not** ingested,
  never assigned to another project (doc §6 failure behavior).

## Step 4 — Fix change discovery

`brain/adapters/documentation/xwiki.py` + `xwiki_http.py`:

- New transport signature (doc §5):
  ```python
  async def list_changed_pages(
      self, spaces: list[str], since: datetime | None = None, *, page_size: int = 50
  ) -> list[dict[str, Any]]: ...
  ```
  returns page metadata (id/ref, `modified`, version, space) for ALL pages in the
  configured spaces, paginated until exhausted.
- Client-side `since` filtering on the normalized `modified` timestamp (the endpoint
  cannot server-side filter by modification time — verified).
- Deterministic ordering by (space, page reference).
- Adapter: `list_changed_documents(spaces, since)` → refs filtered by `since`.
- **Acceptance:** >200 pages discovered via pagination; only pages modified after `since`.

## Step 5 — Durable documentation watermark

- Reuse `SyncWatermarkRepository.get_or_create("xwiki", f"project:{project.id}:space:{space}")`.
- No watermark → **initial full sync** of mapped spaces (doc §11).
- Watermark persists across restarts (already Postgres-backed).
- **Advance rule (doc §4):** watermark advances only when the cycle had zero
  ingestion failures for that (project, space); failed pages keep the watermark so
  they are retried next cycle.

## Step 6 — Reconciliation runtime

`brain/scheduler/reconciliation.py` → `reconcile_documentation(report)`:

```text
for each documentation port (XWiki adapter):
    for each project with a mapped xwiki space ref:
        watermark = get_or_create(provider=xwiki, key=project:<id>:space:<space>)
        refs = port.list_changed_documents(spaces=[space], since=watermark)
        for ref in refs:
            project = resolve_project_for_page(ref)      # Step 3
            artifact = port.fetch_document(ref)          # Step 2 mime/syntax
            await document_ingestion.ingest(project_id, artifact, source_uri=ref.external_id)
        advance watermark on zero failures
```

- Orchestration only — no parsing/persistence logic in the scheduler (doc §1/§19).
- Per-page `try/except` isolation; failures counted (`failed`, with provider/project/
  space/page/version/stage context in logs) — doc §13.
- Summary log per cycle (doc §17):
  `xwiki reconciled project=<id> space=<s> since=<t> discovered=N ingested=M failed=K watermark=<t>`.
- `report.documentation_checked`/new `documentation_synced` fields.

## Step 7 — `DocumentationCatalogSyncService` fix

- Its `ingest_document(ref, project_id)` now **delegates to `DocumentIngestionService`**
  (fetch → ingest) instead of creating a bare Document shell (doc §7/§8).
- Container: construct and register it as `services["documentation_sync"]`; wire the
  scheduler to the same `DocumentIngestionService` instance.

## Step 8 — Configuration

- No new static settings for spaces (they come from `project.external_refs`, doc §18).
- Add only: `BRAIN_DOCUMENTATION_XWIKI_SPACES`-independent page size default (50) as a
  constant in the adapter; wiki/credentials/URL already configurable.

## Step 9 — Tests

`tests/application/test_xwiki_ingestion.py` (+ adapter/parser tests), covering doc §16:

1. Parser registry construction contains expected parsers.
2. XWiki payload → `SourceArtifact` (content, `text/x-xwiki`, version, title, space, parent, modified, ref).
3. `XWikiSyntaxParser` parses headings/lists/code/links/macros-stripped.
4. Space → project mapping; unknown space → unmapped result.
5. Initial sync (no watermark, 3 pages) → 3 documents + watermark stored.
6. Incremental sync (watermark T1; A modified < T1, B > T1) → only B ingested.
7. Pagination > one response limit.
8. Restart: sync 1, new container, sync 2 resumes from watermark.
9. Idempotency: same page/version twice → 1 Document, 1 Version, no duplicate nodes.
10. Changed content → new DocumentVersion + `DocumentChanged`.
11. Failure isolation: one malformed page does not block others; watermark not advanced.
12. Scheduler integration: `reconcile_documentation` end-to-end (Postgres).

## Verification

```bash
uv run ruff format tests brain
uv run ruff check tests brain
uv run mypy brain
uv run pytest -q          # with the live stack stopped
docker build -t brain:latest . && docker compose up -d
```

## Out of scope (doc "Non-Goals")

Attachments, full page-tree, link graph, images, macros expansion, deleted-page
reconciliation, XWiki webhooks — all explicitly deferred; TODO noted in code for
deletion support (doc §12).

## Definition of Done

All checkboxes from the doc's Definition of Done are covered by Steps 1–9
(production parser registration, format match, space mapping, real `since`,
pagination, no hardcoded `Main`, durable watermark, scheduler performs ingestion,
routing through `DocumentIngestionService`, initial + incremental sync, restart
resume, no duplicates, failure isolation, tests, credential-safe logs).