# Refactoring Implementation Plan

This plan is based on `README.md` and a first pass through the current repository. The goal is to evolve the existing code into the modular, persistent, event-driven coding-agent system described in the README without replacing working pieces unnecessarily.

## Current-State Assessment

### Existing Modules And Responsibilities

- `agent_core/agent_core/main.py` exposes the current FastAPI application and initializes SQLAlchemy schema creation plus LangGraph Postgres checkpoint setup.
- `agent_core/agent_core/models.py` contains SQLAlchemy ORM tables for projects, planning sessions, documents, chunks, clarification questions, plan versions, plan nodes, provisioning jobs, external artifacts, and context capsules.
- `agent_core/agent_core/services/` contains application services for project planning, document ingestion, context capsules, and provisioning jobs.
- `agent_core/agent_core/skills/` contains a small skill abstraction and several early planning-related skill implementations. The active runtime registry currently registers only `ambiguity_assessment` and `planning_decomposition`.
- `agent_core/agent_core/workflow/` contains an initial LangGraph planning workflow with skill routing, question persistence, plan persistence, and context capsule creation.
- `agent_core/agent_core/adapters/` contains early OpenProject, Neo4j, and Weaviate adapters, but these are not yet isolated behind formal port interfaces.
- `infra/agent_trigger/app/` contains the OpenProject webhook receiver, event normalization, HMAC verification, synchronous PostgreSQL event storage, Redis queue push, worker loop, OpenProject fetch logic, and a coding-agent placeholder.
- `infra/postgres/init/01-agent-schema.sql` creates webhook inbox, job, and OpenProject context snapshot tables directly at container initialization.
- `src/` contains the older Ada agent implementation with parser, analyzer, generator, executor, and simple code graph experiments.
- `sample_project/` is available as the required E2E fixture target.

### Code Already Usable

- FastAPI route composition and health endpoint in `agent_core`.
- Basic planning data model for projects, sessions, documents, plan versions, plan nodes, relations, and context capsules.
- Markdown document upload and chunking.
- Pydantic plan hierarchy validation for Vision to Capability to Epic to Story to Task.
- Initial LangGraph planning workflow and Postgres checkpointer wiring.
- OpenProject webhook intake that persists before queueing.
- HMAC webhook signature verification.
- Redis-backed event worker skeleton.
- Existing OpenProject provisioner script for bot token and webhook setup.
- Early AST, Tree-sitter, and LSP experiments in `src/parser/` that can inform repository analysis.

### Code To Move Or Wrap

- Wrap `infra/agent_trigger/app/storage.py` behind a webhook inbox port, then migrate it to async SQLAlchemy repositories and Alembic migrations.
- Wrap `infra/agent_trigger/app/openproject_client.py` and `agent_core/adapters/openproject.py` behind a single OpenProject port before expanding behavior.
- Move reusable `src/parser` repository-analysis logic into a new repository analysis adapter under `agent_core`, keeping the old `src` path as compatibility or fixture code until callers are migrated.
- Move ad hoc status and event parsing logic into typed domain event models and deterministic event classification services.
- Wrap `StructuredLLM` behind an LLM port so skills depend on typed generation capabilities rather than a concrete HTTP client.
- Introduce explicit repository path and command policies before any code-writing workflow uses `src/execution` or shell execution logic.

### Duplicate Or Obsolete Implementations

- `src/agent/core.py` and `agent_core` represent separate agent designs. Treat `src/` as legacy/reference code, not the future application root.
- There are two OpenProject client directions: the webhook worker client under `infra/agent_trigger/app/` and the async adapter under `agent_core/adapters/`. These should converge behind one normalized adapter.
- Database schema creation is split between direct SQL initialization and SQLAlchemy `create_all()`. This should become Alembic-managed migrations.
- Planning logic exists both as service methods using direct LLM calls and as LangGraph skill nodes. Consolidate into workflow plus skills while preserving public API behavior.
- The README mentions docs and migration artifacts that are not present yet.

### Existing Database And Webhook Contracts

- Webhook events are persisted in `pm_webhook_events` with source, type, external IDs, headers, payload, processing status, retry count, and error message.
- Jobs are represented in `agent_jobs`, linked to webhook events.
- OpenProject context snapshots are stored in `pm_context_snapshots`.
- The webhook receiver returns an accepted response with `event_id`, normalized `event_type`, and work package ID after persistence and queue push.
- Current duplicate delivery handling is incomplete because no stable external event fingerprint or idempotency key is enforced.

### Test Coverage And Gaps

- `test_ada.py` is a script-style smoke test for the legacy `src` agent. It is not a pytest suite and contains mojibake characters in output strings.
- No discovered first-class unit tests cover the new planning core, database models, workflow routing, adapters, webhook inbox, or idempotency behavior.
- No migrations, contract tests, workflow tests, golden datasets, or E2E scenario are present.
- No current safety tests cover repository path containment or command execution policy.

### Migration Risks

- Replacing `create_all()` with Alembic can break local startup if migrations are incomplete.
- Unifying webhook and core database access can break the currently working event intake path.
- Moving old repository-analysis code too early can strand useful experiments before the new repository port is ready.
- Direct OpenProject API changes can duplicate work packages or comments without outbound idempotency markers.
- LangGraph checkpoint setup currently happens on API startup, so schema or connection failures can prevent the API from serving health checks.
- The Compose file still contains a commented llama.cpp service despite the README saying LLM hosting should not be added to this project.
- The Compose network uses a configured fixed subnet, which the README warns should not become an application assumption.

## Refactoring Principles

- Keep the Python distribution and import root as `agent_core` for the first migration.
- Preserve the current planning API behavior until replacement workflows are covered by tests.
- Add ports and wrappers before moving implementations.
- Convert database state to migrations before adding more tables.
- Keep domain models, skill contracts, policies, and ports vendor-independent.
- Make every external mutation idempotent before enabling automated OpenProject or repository side effects.
- Make repository write boundaries and command execution policy mandatory before coding-agent implementation.

## Phase 0: Assessment And Safety Net

Objective: document the current state and establish a reliable baseline before refactoring.

Tasks:

- Add `docs/current-state-assessment.md` using the assessment in this plan as the starting point.
- Add ADRs for keeping `agent_core`, introducing ports/adapters, migrating to Alembic, and enforcing mounted repository boundaries.
- Record current startup expectations for `docker-compose.yml`, `agent_core`, and `infra/agent_trigger`.
- Run the legacy smoke script and any available pytest discovery; record failures and environment requirements.
- Add import smoke tests for `agent_core.main`, `models`, `schemas`, `skills`, and `workflow`.
- Add a migration map from `src/`, `infra/agent_trigger`, and current adapters into the target package layout.
- Remove no modules in this phase.

Acceptance criteria:

- Existing behavior is documented.
- Current tests or smoke checks are recorded with pass/fail status.
- `agent_core` imports compile in the intended environment.
- Refactor risks have owners and mitigation notes.

## Phase 1: Domain Foundation And Configuration

Objective: create stable typed boundaries that the rest of the system can use.

Tasks:

- Create `agent_core/domain/` for enums, identifiers, projects, requirements, plans, tasks, feedback, evidence, verification, and events.
- Create `agent_core/ports/` for project repository, event inbox, checkpoint, OpenProject, graph store, vector store, repository filesystem, command runner, artifact store, and LLM generation.
- Split `config.py` into `config/settings.py`, logging configuration, and agent definition loading.
- Add `.env.example` matching the README variables and map existing Compose environment names to settings.
- Replace `BaseSettings` field names that diverge from the README, or add compatibility aliases during migration.
- Introduce Alembic and generate the first migration from the current SQLAlchemy models plus webhook tables.
- Replace direct `Base.metadata.create_all()` with explicit migration documentation and a development-only bootstrap command.
- Add unit tests for settings validation, domain enum conversions, and plan hierarchy rules.

Acceptance criteria:

- Domain and port modules do not import FastAPI, SQLAlchemy ORM models, OpenProject clients, Neo4j, Weaviate, Redis, or concrete LLM clients.
- A clean database can be migrated from zero.
- Existing API routes can still start against the migrated schema.

## Phase 2: Skill And Agent Runtime

Objective: make skills replaceable and workflow execution dependent on typed contracts instead of concrete classes.

Tasks:

- Add skill manifests with stable names, versions, input schema, output schema, side-effect declaration, and required tools.
- Convert `BaseSkill` to use immutable/default-safe Pydantic fields and formal input/output schema validation.
- Register all existing skills through manifest loading, including skills that are currently present but not active in `build_skill_registry()`.
- Add duplicate, missing, incompatible, and side-effect policy checks in the registry.
- Move direct LLM usage in `PlanningService` into skill execution paths or a compatibility wrapper.
- Add agent definitions for planning, coding, and verification, initially with only planning enabled.
- Add a generic LangGraph skill-node adapter that resolves skills by registry name.
- Add fake skill test harnesses for workflow tests.

Acceptance criteria:

- Required planning skills are discovered from manifests.
- Duplicate or malformed manifests fail with clear errors.
- A planning graph can execute with fake skills and no external LLM.

### Agent Platform Foundation Update

The general agent platform foundation has been added under `agent_core/agent_core/agent_platform/`.

- Common lifecycle and request/result contracts are in `agent_platform/agents/base/`.
- Planning, coding, and verification agents now have independent config, state, workflow, request, and result modules.
- Agent creation uses the registry-backed `AgentFactory`; default builders are registered without factory conditionals.
- `AgentOrchestrator` coordinates lifecycle, persistence, structured events, approval gates, and high-level transitions without agent-specific business logic.
- Platform adapter namespaces expose infrastructure-facing interfaces over the existing ports.
- Example configuration is in `agent_core/agent-platform.example.json`.
- Detailed architecture is documented in `docs/agent-platform-architecture.md`.
- Migration notes are documented in `docs/agent-platform-migration-notes.md`.
- Implementation results are recorded in `docs/agent-platform-implementation-results.md`.
- PostgreSQL platform checkpoint/result persistence is recorded in `docs/agent-platform-postgres-persistence-results.md`.
- API integration for platform execution is recorded in `docs/agent-platform-api-integration-results.md`.
- Event orchestration through the platform is recorded in `docs/agent-platform-event-orchestration-results.md`.
- Bounded multi-agent flow orchestration is recorded in
  `docs/agent-platform-flow-orchestration-results.md`.
- Production request handoffs from persisted transition context are recorded in
  `docs/agent-platform-transition-resolver-results.md`.
- Durable aggregate flow persistence, approval, and typed resume are recorded in
  `docs/agent-platform-flow-persistence-results.md`.
- Interrupted-flow leases, heartbeat, discovery, and exact-request recovery are recorded in
  `docs/agent-platform-flow-recovery-results.md`.
- PostgreSQL flow queueing and the automatic-heartbeat worker are recorded in
  `docs/agent-platform-background-worker-results.md`.
- Independent Planning, Coding, and Verification LangGraph workflows are recorded in
  `docs/agent-platform-internal-workflows-results.md`.

## Phase 3: Persistence And Event Ingestion

Objective: unify webhook intake, queueing, leasing, retries, and workflow resume.

Tasks:

- Move webhook event contracts into typed domain event models.
- Wrap the current `EventStore` behind an inbox port, then migrate implementation to async SQLAlchemy.
- Add event fingerprint/idempotency keys for duplicate OpenProject webhook delivery.
- Add Redis queue abstraction and worker lease/retry logic with retry classification.
- Move `agent_jobs` into a general event-processing or workflow-execution table.
- Add dead-letter state and retry-at timestamps.
- Integrate inbox events with project orchestrator routing.
- Add LangGraph Postgres setup command under `infra/scripts/setup_langgraph_persistence.py`.
- Ensure waiting planning threads can resume after restart.

Acceptance criteria:

- Webhook handler persists before returning.
- Duplicate webhook delivery does not create duplicate processing.
- Worker retry behavior is deterministic and observable.
- A waiting workflow resumes using persisted checkpoint state.

## Phase 4: OpenProject Adapter And Feedback Loop

Objective: make OpenProject a human-facing projection and instruction channel with idempotent outbound writes.

Tasks:

- Merge the two OpenProject clients into one normalized async adapter behind a port.
- Add semantic mapping for work package types, statuses, priorities, approvals, and verification status.
- Store external artifact mappings and outbound idempotency markers for create/update/comment operations.
- Add reconciliation snapshots that preserve human edits before agent updates.
- Add self-generated webhook echo detection without suppressing later human edits.
- Implement feedback classification for requirement changes, plan feedback, approval, rework request, pause, resume, and cancellation.
- Add approval records and explicit resume logic for planning and task completion approvals.
- Update `infra/openproject/provision` for idempotent discovery of types, statuses, custom fields, webhooks, permissions, and sample binding.

Acceptance criteria:

- Agent-created work packages and comments are not duplicated.
- A human comment can resume the correct workflow thread.
- Agent echo webhooks are ignored while later human edits are processed.

## Phase 5: Repository Analysis

Objective: provide safe, queryable repository context for planning, coding, and verification.

Tasks:

- Add mounted repository bindings with repository key, mount path, access mode, write allowlist, denylist, and command allowlist.
- Implement path containment and symlink-safe path validation.
- Wrap legacy AST, Tree-sitter, and LSP code behind repository analysis ports.
- Add Git snapshot, diff, branch, and working-tree status support.
- Add symbol and relationship persistence tables.
- Project code symbols and relationships into Neo4j.
- Add Weaviate upsert/search for repository context where useful.
- Add fallback behavior when LSP is unavailable.
- Add tests for path traversal rejection and repository fixture indexing.

Acceptance criteria:

- `sample_project` symbols and relationships are queryable.
- Traversal outside the configured mount is rejected.
- Missing LSP produces a warning and deterministic fallback.

## Phase 6: Complete Planning Agent

Objective: complete the planning workflow described by the README.

Tasks:

- Implement the required planning skills: document ingestion, requirement extraction, ambiguity assessment, repository inspection, implementation status classification, plan decomposition, dependency validation, OpenProject projection, Neo4j projection, Weaviate projection, and context capsule assembly.
- Split large README/document ingestion into chunked, evidence-preserving processing.
- Store normalized requirements, constraints, assumptions, decisions, risks, and evidence as domain state.
- Classify existing implementation as complete, partial, missing, conflicting, or unverifiable.
- Validate plan hierarchy, dependencies, cycles, orphan tasks, and acceptance criteria.
- Project epics, stories, tasks, statuses, acceptance criteria, and evidence to OpenProject idempotently.
- Version plans and preserve old versions when feedback changes requirements.

Acceptance criteria:

- Large README ingestion works.
- Requirements include evidence references.
- Blocking ambiguities interrupt the workflow.
- Existing implementation status affects generated tasks.
- OpenProject, Neo4j, and Weaviate projections are rebuildable and idempotent.

## Phase 7: Complete Coding Agent

Objective: implement bounded code changes for approved tasks.

Tasks:

- Add coding workflow graph with task selection, context capsule loading, policy checks, implementation attempt, quality checks, evidence capture, and retry decision.
- Add safe command runner using argument arrays, allowlisted commands, timeout, output limits, and secret redaction.
- Add repository write tracking so only allowed paths can be changed.
- Add branch/diff handling and attempt rollback support.
- Add coding skills for context interpretation, patch proposal, patch application, failure interpretation, and progress summarization.
- Persist attempts, changed files, command outputs, test results, and evidence.
- Update OpenProject task progress with bounded, idempotent comments.

Acceptance criteria:

- An approved sample task changes only allowed paths.
- Quality commands run and persist evidence.
- Failed checks cannot produce a success state.
- Attempt rollback is available and audited.

## Phase 8: Complete Verification Agent

Objective: independently verify task completion against requirements and acceptance criteria.

Tasks:

- Add verification workflow graph with diff review, test evidence review, acceptance matrix generation, decision, and rework routing.
- Add verification skills for acceptance evaluation, regression risk review, test adequacy, and final evidence summary.
- Require mandatory acceptance criteria to pass before task completion.
- Add changes-required flow that links a new coding attempt to the verification failure.
- Add configurable human override and audit record.
- Project verification status and evidence back into OpenProject.

Acceptance criteria:

- Verification reads actual diff and test evidence.
- Failed mandatory criteria block completion.
- Changes-required starts a linked new attempt.
- Human override is audited.

Implementation status on 2026-07-24:

- Complete: independent verification graph, actual diff and command review, typed mandatory
  acceptance matrix, modular test adequacy and regression assessment, security/configuration
  review, final evidence summary, persisted per-node state, and verdict routing.
- Complete: the application transition resolver converts `changes_requested` into a linked coding
  rework request when a prepared rework attempt is available.
- Complete: configuration-driven Verification override gates, typed override commands, immutable
  original results, and durable PostgreSQL-backed actor/reason/reference audit records.
- Complete: configuration-driven OpenProject projection maps Verification verdicts to semantic
  work-package statuses, adds bounded evidence comments, and records human override history without
  mutating the original Verification result.
- Complete: projection uses durable work-package mappings, idempotent outbound operations,
  reconciliation snapshots, retry-safe deterministic keys, and managed adapter lifecycles.
- Phase 8 is complete. Live OpenProject end-to-end validation remains in Phase 9.

## Phase 9: E2E Hardening And Documentation

Objective: make the system operable from a clean clone and prove the sample flow.

Tasks:

- Complete: add an opt-in E2E test using `sample_project`, real PostgreSQL, and a provisioned test
  OpenProject project; see `docs/phase-9-e2e-results.md`.
- Add `infra/scripts/smoke_test.py` covering service readiness and a minimal planning-to-verification path.
- Add operations, troubleshooting, testing, data model, OpenProject integration, and architecture docs.
- Update Compose services to match the README: `agent-trigger`, `agent-worker`, optional `agent-api`, Postgres, Redis, Neo4j, Weaviate, and OpenProject.
- Remove or document the commented llama.cpp Compose service so the project does not imply local LLM hosting.
- Add `host.docker.internal` guidance for Docker host, LAN machine, WSL, and internal DNS deployments.
- Add metrics and structured logging fields for correlation, causation, project, repository, thread, execution, skill run, webhook event, work package, agent, and workflow stage.
- Add golden datasets for requirement extraction, ambiguity assessment, implementation classification, plan decomposition, acceptance evaluation, and failure classification.

Acceptance criteria:

- Clean-clone setup is documented.
- All services except the external llama.cpp server start through the documented infrastructure path.
- Smoke test verifies dependencies and sample flow.
- Test suites pass or environment-dependent exclusions are explicitly documented.

## Suggested Work Order

1. Finish Phase 0 documentation and baseline tests.
2. Convert database handling to Alembic before adding more durable state.
3. Introduce ports and manifest-driven skills before expanding workflows.
4. Unify webhook ingestion and OpenProject adapter before adding new OpenProject side effects.
5. Enforce repository and command safety before any coding-agent implementation.
6. Build the planning vertical slice fully before starting coding and verification.

## Initial Task Backlog

- Create `docs/current-state-assessment.md`.
- Create ADR directory and initial ADRs.
- Add pytest import smoke tests for the current core package.
- Add Alembic scaffolding for `agent_core`.
- Add domain and port package skeletons with no adapter dependencies.
- Add skill manifest format and registry validation.
- Add event idempotency fingerprint for OpenProject webhook payloads.
- Add repository binding model and path containment policy.
- Add a compatibility wrapper for legacy `src/parser` repository analysis.
- Add first workflow test using fake skills and in-memory adapters.
