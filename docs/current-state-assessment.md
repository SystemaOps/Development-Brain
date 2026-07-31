# Current-State Assessment

This assessment is the Phase 0 baseline for refactoring the repository toward the modular, persistent, event-driven coding-agent system specified in `README.md`.

## Existing Modules And Responsibilities

- `agent_core/agent_core/main.py` defines the current FastAPI application, includes route modules, creates SQLAlchemy tables on startup, and sets up LangGraph Postgres checkpoint tables.
- `agent_core/agent_core/config.py` loads required environment settings at import time through Pydantic Settings.
- `agent_core/agent_core/db.py` owns the SQLAlchemy async engine, session factory, declarative base, and development-style `create_schema()` helper.
- `agent_core/agent_core/models.py` defines ORM tables for projects, planning sessions, documents, document chunks, clarification questions, plan versions, plan nodes, plan relations, external artifacts, provisioning jobs, and context capsules.
- `agent_core/agent_core/schemas.py` defines API-facing Pydantic models and plan hierarchy validation.
- `agent_core/agent_core/services/` contains application services for project planning, document ingestion, context capsule creation, and provisioning jobs.
- `agent_core/agent_core/skills/` contains the current skill abstraction, registry, router, and several planning-related skills. The active registry currently registers only `ambiguity_assessment` and `planning_decomposition`.
- `agent_core/agent_core/workflow/` contains an initial LangGraph planning workflow and in-memory store setup.
- `agent_core/agent_core/adapters/` contains early OpenProject, Neo4j, and Weaviate adapters.
- `infra/agent_trigger/app/` contains a separate webhook service with OpenProject event normalization, HMAC signature verification, PostgreSQL event storage, Redis queue push, worker processing, OpenProject API fetches, and a coding-agent placeholder.
- `infra/postgres/init/01-agent-schema.sql` creates webhook inbox, job, and context snapshot tables directly during container initialization.
- `infra/openproject/provision/ensure_agent_bot_token_webhook.rb` provisions an OpenProject bot token and webhook.
- `src/` contains the older Ada agent implementation with parser, analyzer, generator, executor, plan executor, and repository-analysis experiments.
- `sample_project/` is the likely fixture for the required end-to-end scenario.

## Code Already Usable

- FastAPI route composition and health endpoint in `agent_core`.
- Basic planning API routes for project creation, document upload, planning sessions, clarification answers, plan drafting, approval, provisioning, and context capsules.
- SQLAlchemy models for much of the existing planning MVP state.
- Markdown upload and chunking.
- Pydantic validation for the Vision to Capability to Epic to Story to Task plan hierarchy.
- LangGraph planning workflow skeleton with skill routing, question persistence, plan persistence, and context capsule creation.
- OpenProject webhook receiver that persists the event before queueing a job.
- HMAC webhook signature verification.
- Redis-backed worker skeleton and OpenProject context snapshot storage.
- OpenProject bot and webhook provisioning script.
- Legacy AST and LSP experiments that can be reused behind a repository-analysis adapter.

## Code To Move Or Wrap

- Wrap `infra/agent_trigger/app/storage.py` behind a webhook inbox port before migrating it to the core package.
- Wrap both OpenProject clients behind one normalized OpenProject port before changing outbound behavior.
- Wrap `agent_core/llm.py` behind an LLM generation port so skills depend on typed generation rather than the concrete HTTP client.
- Move or wrap reusable code from `src/parser/` into a repository analysis adapter after repository binding and path policy exist.
- Move event parsing and status mapping into deterministic domain services.
- Move database creation from `create_all()` and container init SQL to Alembic migrations.
- Move direct LLM planning logic from `PlanningService` into skill-driven workflow execution or keep it behind a temporary compatibility service.

## Duplicate Or Obsolete Implementations

- `src/agent/core.py` and `agent_core` are separate agent designs. `agent_core` should remain the target import root; `src/` should be treated as legacy/reference until migrated.
- Two OpenProject clients exist: a synchronous worker client under `infra/agent_trigger/app/` and an async adapter under `agent_core/adapters/`.
- Database schema handling is split between SQLAlchemy `create_all()` and direct SQL files in `infra/postgres/init`.
- Planning execution exists both as direct service methods and as a LangGraph workflow.
- `agent_core/api/planning.py` currently defines `POST /v1/planning/sessions/{session_id}/run` twice. The second definition appears to use an obsolete `PlanningWorkflowRunner(db)` constructor.
- The Makefile and Compose file expose a local llama.cpp profile, while the target README states the application should use an externally hosted LLM.

## Existing Database And Webhook Contracts

- `pm_webhook_events` stores OpenProject webhook payloads with source, event type, external project/work-package/comment IDs, headers, payload, received timestamp, processing status, retry count, processed timestamp, and error message.
- `agent_jobs` stores queue-facing job rows linked to webhook events.
- `pm_context_snapshots` stores fetched OpenProject work-package and activity payload snapshots.
- The webhook handler returns after event persistence and Redis enqueue with `status`, `event_id`, `event_type`, and `work_package_id`.
- Current webhook idempotency is incomplete because no durable event fingerprint or external idempotency key is enforced.

## Test Coverage And Known Gaps

- `test_ada.py` is a script-style legacy smoke test and is also discoverable by pytest because its helper functions start with `test_`.
- There was no dedicated `tests/` directory before Phase 0.
- New planning core import smoke tests were added in Phase 0.
- No current tests cover database migrations, webhook duplicate delivery, queue leasing, OpenProject outbound idempotency, repository path policies, workflow resume, or skill contract compatibility.
- No golden datasets, workflow tests, adapter contract tests, or end-to-end OpenProject scenario exist yet.

## Migration Risks

- Replacing `create_all()` with Alembic can break local startup if the migration does not exactly reflect the current schema.
- Merging webhook intake into the core package can break the currently working persist-before-queue flow.
- Changing OpenProject projection behavior before idempotency exists can create duplicate work packages or comments.
- Moving `src/parser` code before repository policy exists can introduce unsafe filesystem access.
- LangGraph checkpoint setup currently runs during API lifespan startup, so database or checkpointer failures can prevent full API startup.
- Configuration is required at import time, so tests and scripts must provide environment variables before importing core modules.
- The repository currently contains unrelated untracked files and a modified `README.md`; Phase 0 should not rewrite or normalize those.

## Phase 0 Decision

Phase 0 should add documentation and safety tests only. It should not remove modules, rename packages, rewrite database state, or change runtime behavior.
