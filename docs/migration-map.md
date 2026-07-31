# Migration Map

This map records where existing code should land as the repository moves toward the target architecture. It is intentionally incremental: wrap first, migrate callers second, remove old paths only after production code no longer references them.

## Target Root

- Keep the distribution and import root `agent_core` for the initial migration.
- Use `agent_core/agent_platform/` as the modular agent-platform boundary for planning, coding, verification, orchestration, runtime dependencies, and factory registration.
- Treat `src/` as legacy/reference code until repository analysis and coding-agent capabilities are safely wrapped.
- Keep `infra/agent_trigger` running until webhook intake and worker behavior are proven behind new ports.

## Current To Target Mapping

| Current path | Target location | Migration action |
|---|---|---|
| `agent_core/agent_core/config.py` | `agent_core/agent_core/config/settings.py` | Split settings, add aliases, keep compatibility import while callers migrate. |
| `agent_core/agent_core/db.py` | `agent_core/agent_core/persistence/` | Add unit-of-work and repositories; replace `create_all()` with Alembic. |
| `agent_core/agent_core/models.py` | `agent_core/agent_core/persistence/sqlalchemy_models.py` | Keep current models until migrations exist; then move or re-export. |
| `agent_core/agent_core/schemas.py` | `agent_core/agent_core/api/schemas/` plus `domain/` | Move API schemas separately from domain contracts. |
| `agent_core/agent_core/enums.py` | `agent_core/agent_core/domain/enums.py` | Move with compatibility re-export. |
| `agent_core/agent_core/services/planning_service.py` | `application/services/` and workflows | Keep public behavior; move direct LLM calls behind skills. |
| `agent_core/agent_core/skills/base.py` | `skills/contracts.py` | Add manifest, input/output validation, and side-effect metadata. |
| `agent_core/agent_core/skills/registry.py` | `skills/registry.py` | Extend to manifest loading and duplicate/incompatible manifest checks. |
| `agent_core/agent_core/workflow/` | `workflow/planning/`, `workflow/coding/`, `workflow/verification/` | Keep current planning graph while adding explicit graphs per agent. |
| `agent_core/agent_core/agents/` | `agent_platform/agents/` | Keep the old registry metadata path for compatibility; new executable agents live under platform modules. |
| `agent_core/agent_core/services/planning_service.py` | `agent_platform/agents/planning/agent.py` plus existing service | PlanningAgent wraps the service through dependency injection while current API callers migrate. |
| `agent_core/agent_core/services/coding_service.py` | `agent_platform/agents/coding/agent.py` plus existing service | CodingAgent wraps one approved coding attempt and delegates bounded execution to the service. |
| `agent_core/agent_core/adapters/openproject.py` | `adapters/openproject/` | Active async adapter now uses the OpenProject port shape and outbound idempotency store; split package later if it grows. |
| `agent_core/agent_core/adapters/neo4j_store.py` | `adapters/graph_store/neo4j.py` | Wrap behind graph-store port. |
| `agent_core/agent_core/adapters/weaviate_store.py` | `adapters/vector_store/weaviate.py` | Wrap behind vector-store port. |
| `agent_core/agent_core/llm.py` | `adapters/llm/openai_compatible.py` | Wrap behind a structured-generation port. |
| `infra/agent_trigger/app/storage.py` | `adapters/persistence/webhook_inbox.py` | Wrap first, then migrate to async SQLAlchemy and Alembic. |
| `infra/agent_trigger/app/event_parser.py` | `domain/events.py` plus `application/event_classification.py` | Convert to typed event envelopes and deterministic classification. |
| `infra/agent_trigger/app/openproject_client.py` | `adapters/openproject/` | Legacy reference only after trigger worker delegation; remove after unified adapter covers all remaining OpenProject behavior. |
| `infra/agent_trigger/app/worker.py` | `workers/event_worker.py` | Queue/lease compatibility remains here; event orchestration now delegates to `agent_core`. |
| `infra/postgres/init/01-agent-schema.sql` | Alembic migrations | Convert schema to migrations; stop relying on init SQL for app-owned tables. |
| `src/parser/` | `adapters/repository_analysis/` | Wrap behind repository-analysis port after path containment policy exists. |
| `src/execution/code_executor.py` | `adapters/command_runner/` | Do not reuse until command allowlist, timeout, output limit, and secret redaction exist. |
| `src/generation/code_generator.py` | Coding skills | Treat as legacy placeholder; replace with typed skill contracts. |
| `src/analysis/code_analyzer.py` | Repository inspection and coding skills | Reuse only through safe repository adapters. |
| `test_ada.py` | `tests/legacy/` or smoke script | Keep as baseline script until pytest suite supersedes it. |

## Removal Rules

- Do not delete legacy code while it is still the only implementation of a capability.
- Do not remove `infra/agent_trigger` until OpenProject webhook persistence, queueing, and worker behavior are covered by tests.
- Do not remove direct service planning paths until the workflow path has parity tests and the API behavior is stable.
- Do not enable coding-agent write behavior until repository write policy and command policy tests pass.
