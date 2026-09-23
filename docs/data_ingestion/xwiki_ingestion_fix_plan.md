# XWiki Data Ingestion — Runtime Fix Plan

## Goal

Make XWiki documentation ingestion operational end-to-end.

Target runtime flow:

```text
XWiki pages
  → DocumentationPort.list_changed_documents()
  → DocumentationPort.fetch_document()
  → SourceArtifact
  → parser registry
  → ParsedDocument
  → DocumentIngestionService
  → Document / DocumentVersion / DocumentNode
  → semantic chunks
  → semantic index
  → knowledge graph
  → durable sync watermark
```

The existing implementation is largely complete at the component level, but the runtime wiring is missing or incomplete.

---

# Current Problems

## 1. Documentation reconciliation is a no-op

File:

```text
brain/scheduler/reconciliation.py
```

Current `reconcile_documentation` does not:

- load a documentation watermark
- call `list_changed_documents`
- fetch changed documents
- resolve the canonical Brain project
- call `DocumentIngestionService`
- persist the updated watermark

### Required Fix

Implement the actual polling/reconciliation flow.

Expected high-level logic:

```python
watermark = watermark_repository.get(...)

changed_refs = await documentation.list_changed_documents(
    since=watermark
)

for ref in changed_refs:
    project = resolve_project(ref)

    artifact = await documentation.fetch_document(ref)

    await document_ingestion.ingest(
        project_id=project.id,
        artifact=artifact,
    )

watermark_repository.save(...)
```

Do not duplicate parsing or document persistence logic in the scheduler.

The scheduler should orchestrate only.

---

# 2. Register runtime document parsers

File:

```text
brain/bootstrap/providers.py
```

Current runtime construction appears to use:

```python
DefaultParserRegistry()
```

without registering the available parsers.

As a result, runtime ingestion fails with errors such as:

```text
no parser registered
```

even though tests work because parsers are manually registered there.

## Required Fix

Register all production parsers when building `DocumentIngestionService`.

At minimum inspect and register the existing implementations for:

```text
Markdown
HTML
PDF
ADR
plain text, if available
```

Example pattern:

```python
registry = DefaultParserRegistry()

registry.register(HtmlParser())
registry.register(MarkdownParser())
registry.register(PdfParser())
registry.register(AdrParser())
```

Use the existing parser interfaces and registration mechanism rather than adding a second registry.

---

# 3. Fix XWiki content format

Relevant files:

```text
brain/adapters/documentation/xwiki.py
xwiki_http.py
```

Current behavior marks XWiki page content as:

```text
text/html
```

but XWiki REST page content may be returned as XWiki syntax such as:

```text
xwiki/2.1
```

This can cause `HtmlParser` to incorrectly parse raw XWiki markup.

## Preferred MVP Fix

Request converted/rendered HTML from XWiki and continue using:

```text
mime_type = text/html
```

Target flow:

```text
XWiki page
  → XWiki REST converted/rendered content
  → HTML
  → HtmlParser
```

If this is not reliably supported by the current REST endpoint, add an explicit XWiki syntax parser.

Do not label raw XWiki syntax as `text/html`.

---

# 4. Implement durable documentation watermarks

Reuse the existing sync watermark infrastructure used by other integrations.

Likely component:

```text
SyncWatermarkRepository
```

Do not introduce a separate XWiki-only persistence model unless required.

## Watermark Scope

Watermarks should be scoped sufficiently to avoid collisions.

Recommended identity:

```text
provider=xwiki
project=<brain_project_id>
source=<xwiki instance / wiki / mapped space>
```

Example logical key:

```text
xwiki:project:<project_uuid>:space:ADAS
```

## Behavior

After a successful reconciliation:

```text
last successful synchronization timestamp/version
```

must survive:

```text
application restart
worker restart
scheduler restart
deployment
```

Do not advance the watermark past documents that failed ingestion unless retry semantics explicitly support it.

---

# 5. Fix `list_changed_pages`

Relevant file:

```text
xwiki_http.py
```

Current issues:

- ignores `since`
- hardcodes `Main`
- hardcodes `limit=200`
- does not reliably identify pages modified after the watermark
- cannot safely sync established projects with more than 200 pages

## Required Fix

Change the API so that the caller can provide:

```python
list_changed_pages(
    spaces=[...],
    since=...,
)
```

or the equivalent existing abstraction.

Required behavior:

```text
only configured/mapped spaces
only pages changed after `since`
pagination until all relevant pages are read
deterministic ordering
```

Do not rely on one fixed page of 200 results.

If the XWiki endpoint cannot server-side filter by modification timestamp, implement:

```text
paginated fetch
→ normalize modified timestamp
→ client-side filter by `since`
```

Document this behavior.

---

# 6. Map XWiki spaces to canonical Brain projects

XWiki documents must not create independent projects implicitly.

The Brain project remains canonical.

External systems are connected through external references.

Expected model:

```text
Brain Project
  ├── OpenProject project reference
  ├── GitLab group/project reference
  └── XWiki space reference
```

Example:

```text
Project
  id = <uuid>

ExternalReference
  provider = xwiki
  resource_type = space
  external_id = ADAS
```

## Required Fix

When an XWiki page is discovered:

```text
ADAS.Requirements.Braking
```

resolve:

```text
space = ADAS
```

then:

```text
ExternalReference(xwiki, space, ADAS)
  → canonical Brain Project
```

Then pass that project ID into the canonical ingestion service.

## Failure Behavior

If no project mapping exists:

- do not silently assign the document to another project
- do not automatically create a Brain project
- log/report an unmapped documentation source
- leave the page eligible for future retry

---

# 7. Route XWiki ingestion through `DocumentIngestionService`

Relevant implementation:

```text
brain/application/document_ingestion.py
```

This must remain the canonical ingestion path.

It already handles:

```text
parser selection
content hashing
Document creation/update
DocumentVersion
DocumentNode tree
ADR decision extraction
semantic chunk creation
DocumentChanged events
```

Do not duplicate this logic in:

```text
DocumentationCatalogSyncService
scheduler
XWiki adapter
XWikiMappingService
```

## Desired runtime path

```text
XWikiDocumentationAdapter.fetch_document()
  → SourceArtifact
  → DocumentIngestionService.ingest(...)
```

If `DocumentationCatalogSyncService` remains in the architecture, either:

1. make it delegate to `DocumentIngestionService`, or
2. limit it clearly to catalog/discovery responsibilities.

It must not become a second incomplete ingestion path.

---

# 8. Decide the role of `DocumentationCatalogSyncService`

Current behavior reportedly:

```text
create Document shell
→ emit DocumentChanged
```

but does not:

```text
parse
version
create nodes
create chunks
index
populate graph
```

## Required Refactor

Choose one clear responsibility.

Recommended:

```text
DocumentationCatalogSyncService
  → discovery / synchronization orchestration only

DocumentIngestionService
  → canonical content ingestion
```

Avoid maintaining two services that both partially create/update documents.

---

# 9. Use `XWikiMappingService` where appropriate

Relevant file:

```text
brain/application/xwiki_sync.py
```

Existing functionality includes:

```text
ref()
to_source_artifact()
document_type_for_page()
emit_changed()
```

Reuse useful mapping logic instead of duplicating it.

However, avoid forcing all XWiki-specific behavior into the canonical ingestion layer.

Desired separation:

```text
XWiki-specific mapping
  → SourceArtifact + metadata

Canonical ingestion
  → document model
```

---

# 10. Hierarchy, links, and attachments

Current methods reportedly return empty collections:

```python
get_children(...) -> []
get_attachments(...) -> []
get_links(...) -> []
```

These should not block the MVP ingestion path.

## Phase 1

Support:

```text
page content
title
space
parent metadata
version
modified timestamp
external reference
document type
```

## Phase 2

Add:

```text
page hierarchy
attachments
cross-page links
embedded images
macros
tables where useful
```

Do not delay basic ingestion waiting for attachment support.

---

# 11. Initial ingestion for established projects

The system must support being connected to an already populated XWiki instance.

Example:

```text
Existing project
  → 2,000 XWiki pages
  → Brain integration enabled today
```

Expected behavior:

```text
no watermark
  → initial full sync of configured/mapped spaces
  → ingest all pages
  → persist watermark
```

Subsequent runs:

```text
existing watermark
  → ingest only changed/new pages
```

Pagination must work for large spaces.

---

# 12. Deleted Pages

Check whether the XWiki API exposes deletions/history sufficiently for reconciliation.

If supported, define canonical behavior for:

```text
page deleted externally
```

Possible Brain behavior:

```text
Document marked deleted/archived
or
external reference marked unavailable
```

Deletion support is desirable but should not block the first operational ingestion implementation.

If not implemented now, add an explicit TODO and test the non-deletion path.

---

# 13. Error Handling

One bad page must not abort the entire reconciliation cycle.

Desired behavior:

```text
Page A → success
Page B → parser failure
Page C → success
```

The sync run should report:

```text
processed=3
succeeded=2
failed=1
```

Log enough context to identify:

```text
provider
project
space
page external ID
version
failure stage
```

Examples of stages:

```text
discovery
fetch
project_resolution
mapping
parsing
ingestion
indexing
graph update
```

---

# 14. Idempotency

Reprocessing the same XWiki page version must not create duplicate:

```text
Document
DocumentVersion
DocumentNode
semantic chunk
graph entities
```

Existing content-hash/version logic in `DocumentIngestionService` should be reused.

Test at least:

```text
same page + same content
→ no duplicate version

same page + changed content
→ new version

same page + metadata-only irrelevant change
→ expected documented behavior
```

---

# 15. Recommended Implementation Order

## Step 1 — Parser Registry

Fix runtime parser registration first.

Acceptance:

```text
manual INGEST_DOCUMENT works in the production service container
```

---

## Step 2 — XWiki Content Format

Ensure `SourceArtifact.mime_type` matches the actual content.

Prefer converted HTML for the MVP.

Acceptance:

```text
normal XWiki page
→ HtmlParser
→ meaningful ParsedDocument structure
```

---

## Step 3 — Project Mapping

Implement:

```text
XWiki space
→ ExternalReference
→ Brain Project
```

Acceptance:

```text
mapped page resolves project
unmapped page is rejected/reportable
```

---

## Step 4 — Change Discovery

Fix:

```text
list_changed_pages
```

including:

```text
configured spaces
since filtering
pagination
modified timestamps
```

---

## Step 5 — Watermark

Wire the existing durable `SyncWatermarkRepository`.

Acceptance:

```text
restart application
→ sync resumes from persisted watermark
```

---

## Step 6 — Reconciliation Runtime

Implement:

```text
scheduler
→ watermark
→ list changes
→ project resolution
→ fetch artifact
→ DocumentIngestionService
→ update watermark
```

---

## Step 7 — Tests

Add end-to-end service tests.

---

# 16. Required Tests

## Parser registration

Test production service construction:

```text
build_services()
→ parser registry contains expected parsers
```

Do not only test manually created registries.

---

## XWiki format mapping

Test:

```text
XWiki API payload
→ SourceArtifact
```

Verify:

```text
content
mime_type
version
title
space
parent
external reference
modified timestamp
```

---

## Project mapping

Test:

```text
XWiki space ADAS
→ Project A
```

and:

```text
unknown space
→ unmapped error/result
```

---

## Initial sync

Given:

```text
no watermark
3 XWiki pages
```

expect:

```text
3 documents ingested
watermark stored
```

---

## Incremental sync

Given:

```text
watermark = T1
page A modified before T1
page B modified after T1
```

expect:

```text
only page B ingested
```

---

## Pagination

Given more pages than one XWiki response limit:

```text
>200 pages
```

expect all relevant pages to be discovered.

---

## Restart behavior

Run:

```text
sync 1
restart/rebuild service
sync 2
```

expect sync 2 to continue from the stored watermark.

---

## Idempotency

Run the same page/version twice.

Expect:

```text
1 canonical Document
1 corresponding DocumentVersion
no duplicate nodes/chunks
```

---

## Changed document

Change page content/version.

Expect:

```text
same Document
new DocumentVersion
updated semantic representation
DocumentChanged emitted
```

---

## Failure isolation

One malformed page should not prevent valid pages from being processed.

---

# 17. Observability

Add structured logging or equivalent diagnostics for each sync cycle.

Recommended summary:

```text
XWiki reconciliation:
project=<uuid>
space=ADAS
since=<timestamp>
discovered=42
fetched=42
ingested=40
unchanged=1
failed=1
watermark=<timestamp>
```

Avoid logging credentials or full sensitive document contents.

---

# 18. Configuration

Avoid hardcoded:

```text
Main
limit=200
superadmin-specific assumptions
```

Use existing application configuration where possible.

Configuration should support:

```text
XWiki URL
wiki
credentials
mapped spaces
page size
polling behavior
```

Project-space relationships should preferably live in canonical/external-reference data rather than static config.

---

# 19. Architecture Constraints

Preserve these boundaries.

## Documentation Adapter

Responsible for:

```text
communicating with XWiki
normalizing external data
producing SourceArtifact
listing changed external documents
```

Must not contain canonical persistence logic.

---

## DocumentIngestionService

Responsible for:

```text
parsing
canonical document persistence
versioning
nodes
semantic chunks
domain events
```

Must not contain XWiki HTTP logic.

---

## Reconciliation Layer

Responsible for:

```text
polling
watermark management
project resolution
orchestration
retry/error isolation
```

Must not duplicate parsing or document persistence.

---

## ExternalReference

Responsible for relationships such as:

```text
Brain Project
↔ XWiki space

Brain Project
↔ OpenProject project

Brain Project
↔ GitLab project/group
```

The Brain Project remains independent and canonical.

---

# 20. Target End State

After implementation, creating/mapping a project with an XWiki space should allow this runtime behavior:

```text
Scheduler tick
    │
    ▼
Load XWiki watermark
    │
    ▼
Find mapped XWiki spaces
    │
    ▼
List pages changed since watermark
    │
    ▼
Resolve page → Brain Project
    │
    ▼
Fetch page
    │
    ▼
SourceArtifact
    │
    ▼
Parser Registry
    │
    ▼
ParsedDocument
    │
    ▼
DocumentIngestionService
    │
    ├── Document
    ├── DocumentVersion
    ├── DocumentNode
    ├── ADR decisions
    ├── semantic chunks
    ├── semantic index
    └── knowledge graph
    │
    ▼
Persist successful watermark
```

---

# Definition of Done

The XWiki integration is considered operational when all of the following are true:

- [ ] production runtime registers document parsers
- [ ] XWiki content format matches the selected parser
- [ ] XWiki spaces can be mapped to Brain projects
- [ ] changed pages can be listed using a real `since` value
- [ ] page discovery supports pagination
- [ ] configured/mapped spaces are used instead of hardcoded `Main`
- [ ] documentation sync has a durable watermark
- [ ] scheduler reconciliation actually performs ingestion
- [ ] XWiki documents are routed through `DocumentIngestionService`
- [ ] initial sync works for an established populated project
- [ ] incremental sync works after the initial sync
- [ ] restart/resume behavior works
- [ ] duplicate ingestion is prevented
- [ ] one broken page does not abort the whole sync
- [ ] unit and integration tests cover the runtime path
- [ ] logs expose sync counts and failures without leaking credentials

---

# Non-Goals for the First Fix

Do not block the initial implementation on:

```text
attachments
full page-tree reconstruction
cross-page link graph
embedded image ingestion
XWiki macros
deleted-page reconciliation
XWiki webhooks
```

These can be implemented after the core ingestion path is proven operational.

The immediate priority is:

```text
XWiki
→ changed page discovery
→ project resolution
→ SourceArtifact
→ DocumentIngestionService
→ semantic index / graph
→ durable watermark
```
