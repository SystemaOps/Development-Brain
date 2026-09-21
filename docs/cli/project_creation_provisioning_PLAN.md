# Implementation Plan — Project Creation & Provisioning Commands

> Companion to `docs/cli/project_creation_provisioning.md`. Implements the two
> requested CLI commands: **`brainctl project create`** (brand-new project
> ecosystem) and **`brainctl project bootstrap`** (connect an existing brain
> project to external projects that already exist).

## Scope

| Command | Semantics | External systems touched |
|---|---|---|
| `brainctl project create <name>` | NEW project everywhere | OpenProject + GitLab + XWiki (provisioned, each optional) |
| `brainctl project bootstrap <brain-id> --openproject <id> [--gitlab <path>] [--xwiki <space>]` | EXISTING external projects | Link refs + OpenProject historical import (existing bootstrap service) |

The doc's `create-canonical` and `provision` are kept out of the CLI surface for
now; `ProjectProvisioningService` exposes them so the API/agents can reuse the
same logic later.

Design principle (doc): the canonical Brain `Project` stays the primary
identity; external projects are representations linked via `ExternalReference`.
Orchestration lives in `ProjectProvisioningService`, never in the CLI command.

---

## Phase 1 — Port Extensions

### 1.1 `WorkManagementPort.create_project`

`brain/ports/work_management.py` — add:

```python
async def create_project(
    self, name: str, description: str | None = None
) -> ExternalReference: ...
```

Returns the provider's project reference (never becomes the brain identity).

### 1.2 New provisioning ports

New file `brain/ports/provisioning.py`:

```python
class ExternalProjects(BaseModel):
    work_management: str | None = None   # existing OpenProject project id
    source_control: str | None = None    # existing GitLab group/project path
    documentation: str | None = None     # existing XWiki space

class SourceControlProvisioningPort(Protocol):
    async def create_project(self, name: str, description: str | None = None) -> ExternalReference: ...

class DocumentationProvisioningPort(Protocol):
    async def create_space(self, name: str) -> ExternalReference: ...
```

Kept separate from `SourceControlPort` (a git-operations port) and
`DocumentationPort` (a read port) so those contracts stay clean.

**Gate:** `ruff`/`mypy` pass with the new protocol definitions.

## Phase 2 — Provider Adapters

### 2.1 OpenProject `create_project`

- `brain/adapters/work_management/openproject_http.py`: `create_project(name, description)`
  → `POST /api/v3/projects` with `{"name", "identifier", "description"}`;
  `identifier` slugified (lowercase, `[a-z0-9_]`).
- `brain/adapters/work_management/openproject.py` (`OpenProjectAdapter`):
  implements the port method; returns `ExternalReference(openproject, project, <id>)`.
- `brain/adapters/work_management/jira.py` (`JiraAdapter`): stub raising
  `NotImplementedError` (proves interchangeability, doc Task 14.6).

### 2.2 GitLab project provisioning

New file `brain/adapters/git/gitlab_provisioning.py`:

```python
class GitLabProjectProvisioningAdapter(SourceControlProvisioningPort):
    def __init__(self, base_url: str, api_key: str, ...): ...
    async def create_project(self, name, description=None) -> ExternalReference: ...
```

- `POST /api/v4/projects` with `{"name", "path", "description"}` (`path` = slug),
  `PRIVATE-TOKEN` header (same auth pattern as `GitLabPullRequestAdapter`).
- Returns `ExternalReference(gitlab, project, <id>, namespace=<path_with_namespace>)`.

### 2.3 XWiki space creation

- `brain/bootstrap/settings.py` (`DocumentationSettings`): add
  `xwiki_user: str = ""`, `xwiki_password: str = ""`.
- `brain/bootstrap/providers.py` (`build_documentation`): pass credentials to
  the `XWikiHTTPTransport` (it already supports Basic auth).
- `brain/adapters/documentation/xwiki_http.py`: `create_space(space)`
  → `PUT /rest/wikis/{wiki}/spaces/{space}` (Basic auth).
- `brain/adapters/documentation/xwiki.py` (`XWikiDocumentationAdapter`):
  implements `DocumentationProvisioningPort.create_space` → `ExternalReference(xwiki, space, "space")`.

**Gate:** adapter unit tests with fake transports (in-memory), matching
`tests/adapters/test_work_management.py` conventions.

## Phase 3 — ProjectProvisioningService

New file `brain/application/provisioning.py`:

```python
class ProjectProvisioningService:
    def __init__(
        self, *,
        projects: ProjectRepository,
        work_management: WorkManagementPort | None,
        source_control: SourceControlProvisioningPort | None,
        documentation: DocumentationProvisioningPort | None,
        bootstrap: OpenProjectProjectBootstrapService | None,
        event_bus: EventBus,
    ): ...

    async def create_canonical(self, name, description=None) -> Project
    async def create_connected(self, name, description=None) -> ProvisioningResult
    async def provision(self, project_id) -> ProvisioningResult
    async def bootstrap(self, project_id, external: ExternalProjects) -> ProvisioningResult
```

Behavior:

- `create_canonical` — canonical `Project` only (INSERT + commit via CLI path).
- `create_connected` — `create_canonical` then `provision`.
- `provision` — for each **configured** provider, call its create method, append
  the returned `ExternalReference` to `project.external_refs`, update + persist.
  Providers that are not configured are skipped with a `details` note (never an
  error): OpenProject adapter built ⇔ `work_management` configured; GitLab ⇔
  `BRAIN_PULL_REQUEST_GITLAB_URL` set; XWiki ⇔ `xwiki_enabled` + credentials.
  Provider failures are caught per-provider, recorded in `details`, and do not
  roll back the canonical project (best-effort provisioning).
- `bootstrap` — link **existing** externals: append
  `ExternalReference(openproject|gitlab|xwiki, ...)` records for each provided
  flag (idempotent — skip refs already present). Does **not** call provider
  create methods. OpenProject historical import stays in the worker
  (`BOOTSTRAP_PROJECT` command, existing `OpenProjectProjectBootstrapService`).

Result model:

```python
class ProvisioningResult(BaseModel):
    project: Project
    refs_added: list[ExternalReference]
    details: list[str]
```

**Gate:** service tests with fake providers (in-memory): full provisioning,
per-provider skip, per-provider failure isolation, bootstrap linking
idempotency, canonical-only fallback.

## Phase 4 — CLI Commands

`brain/cli/commands/projects.py`:

### 4.1 `create` — NEW project everywhere

```bash
brainctl project create <name> [--description TEXT]
```

```python
@project_app.command("create")
async def create(name: str, description: str | None = None) -> None:
    # cli_container → services["project_provisioning"].create_connected(...)
    # print: created <uuid> <name>, then one line per external ref
    # (openproject/gitlab/xwiki) or a "skipped: <reason>" note per provider
```

### 4.2 `bootstrap` — connect EXISTING external projects

```bash
brainctl project bootstrap <project-id> \
    [--openproject <id>] [--gitlab <group/project>] [--xwiki <Space>]
```

Backward compatible: the current positional
`bootstrap <project-id> <external-project-id>` maps to `--openproject`.

```python
@project_app.command("bootstrap")
async def bootstrap(
    project_id: str,
    external_project_id: str | None = None,   # legacy alias of --openproject
    openproject: str | None = None,
    gitlab: str | None = None,
    xwiki: str | None = None,
) -> None:
```

Flow:

1. Load the canonical project; exit 1 if missing.
2. `services["project_provisioning"].bootstrap(project_id, ExternalProjects(...))`
   — links refs inline (CLI commits on exit).
3. If `--openproject` given: enqueue `BOOTSTRAP_PROJECT` (same as today) so the
   worker imports history asynchronously; print "bootstrap queued".
4. Print linked refs + notes (GitLab/XWiki are link-only in this milestone).

**Gate:** CLI tests (`tests/test_phase30_cli.py` conventions) — `create` prints
canonical + provider refs/skips; `bootstrap` with flags persists refs; legacy
positional form still queues the import.

## Phase 5 — Container Wiring

`brain/bootstrap/providers.py`:

- Build `GitLabProjectProvisioningAdapter` when `pull_requests.gitlab_url`
  is set (same credentials as the MR adapter).
- `build_documentation` passes `xwiki_user`/`xwiki_password`.
- New `build_project_provisioning(settings, repos, work_management, bootstrap)`
  returning `ProjectProvisioningService | None` (or always-built with `None`
  providers when nothing is configured).
- Register as `services["project_provisioning"]`.

`brain/application/__init__.py` and `brain/bootstrap/container.py`: export /
surface the service (container accessor optional — CLI uses
`container.services[...]` like other services).

## Phase 6 — Tests & Verification

- `tests/application/test_provisioning.py` — service scenarios (see Phase 3
  gate).
- `tests/adapters/test_gitlab_provisioning.py` — GitLab adapter with a fake
  HTTP surface (urllib monkeypatch or fake transport injection).
- XWiki `create_space` test with fake transport; settings auth round-trip.
- Extend `tests/test_phase30_cli.py` with `create` + `bootstrap` command tests.
- OpenProject `create_project` adapter test (fake transport), Jira stub raises.
- Full chain:

```bash
uv run ruff format tests brain
uv run ruff check tests brain
uv run mypy brain
uv run pytest -q
```

## Order

1 → 2 → 3 → 4 → 5 → 6 (ports first so adapters compile against contracts).

## Known boundaries

- GitLab/XWiki are **link-only** in `bootstrap` (no historical import yet —
  OpenProject import exists; GitLab push/ingest and XWiki doc import remain
  future work).
- `provision`/`create-canonical` are implemented in the service but not exposed
  as CLI commands yet (doc's `create-canonical` and `provision` commands can be
  added later with no service changes).
- Provider creation is best-effort: one provider failing never deletes the
  canonical project or blocks the others.