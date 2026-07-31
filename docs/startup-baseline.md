# Startup Baseline

This document records the startup expectations observed during Phase 0. It is descriptive, not a new operating guide.

## Repository Entrypoints

- `main.py` runs the legacy Ada agent demo from the root package layout.
- `agent_core/agent_core/main.py` runs the newer FastAPI planning core.
- `infra/agent_trigger/app/main.py` runs the OpenProject webhook receiver.
- `infra/agent_trigger/app/worker.py` runs the Redis worker that claims queued webhook jobs and delegates event orchestration to `planning-agent-core`.

## Package Layout

- There is no root `pyproject.toml`.
- `agent_core/pyproject.toml` defines the newer core package.
- Root `requirements.txt` applies to the legacy Ada agent.
- `agent_core/requirements.txt` applies to the planning core container/dev environment.
- `infra/agent_trigger/requirements.txt` applies to the webhook receiver and worker image.

## Makefile

- `make setup` runs `python infra/scripts/generate_env.py` and creates `models` and `workspace` directories.
- `make up` runs `docker compose up -d --build`.
- `make up-llm` runs `docker compose --profile llm up -d --build`.
- `make logs` follows `openproject-provision`, `agent-webhook`, and `agent-worker` logs.
- `make test-webhook` runs `infra/scripts/test_webhook.sh`.

## Docker Compose

- Compose services include Postgres, Redis, OpenProject, OpenProject provisioning, `agent-webhook`, `agent-worker`, Neo4j, Weaviate, and `planning-agent-core`.
- A commented llama.cpp profile is still present. The target README says the application should not host an LLM inside this Compose project.
- `agent-worker` mounts `./infra/workspace:/workspace`.
- `agent-worker` calls `planning-agent-core` at `PLANNING_AGENT_CORE_URL`.
- `planning-agent-core` does not currently mount a repository workspace.
- `planning-agent-core` uses `LLM_BASE_URL=http://localhost:8080/v1`, which points inside the container rather than the Docker host unless overridden.
- The Compose network uses `${CODING_AGENT_DOCKER_SUBNET}`.

## Planning Core Startup

Expected command from Compose:

```bash
uvicorn agent_core.main:app --host 0.0.0.0 --port 8000
```

Required environment variables for import/startup include:

- `DATABASE_URL`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `OPENPROJECT_BASE_URL`
- `OPENPROJECT_API_KEY`
- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`

Startup behavior:

- Imports `agent_core.models` for table registration.
- Calls `create_schema()` during FastAPI lifespan startup.
- Initializes LangGraph Postgres checkpoint tables during lifespan startup.
- Uses an in-memory LangGraph store for development.

## Agent Trigger Startup

Expected webhook command from Compose:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8090
```

Expected worker command from Compose:

```bash
python -m app.worker
```

Required environment variables include:

- `DATABASE_URL`
- `REDIS_URL`
- `REDIS_QUEUE`
- `WEBHOOK_SIGNATURE_SECRET`
- `WEBHOOK_REQUIRE_SIGNATURE`
- `WEBHOOK_SIGNATURE_HEADER`
- `PLANNING_AGENT_CORE_URL`

Current behavior:

- Webhook receiver normalizes and stores incoming OpenProject payloads.
- Webhook receiver pushes the stored event ID to Redis.
- Worker claims an `agent_jobs` lease for the stored event ID.
- Worker delegates event orchestration to `POST /v1/events/{event_id}/orchestrate` on `planning-agent-core`.
- Worker uses the existing retry and dead-letter policy when core orchestration is unavailable or fails.

## Baseline Gaps

- Database lifecycle is not migration-managed yet.
- Webhook tables are created through container init SQL, while planning tables use SQLAlchemy `create_all()`.
- No documented clean-clone startup path exists for the full target architecture.
- Planning core owns event orchestration; the trigger worker remains as queue and lease compatibility infrastructure.
- Local LLM hosting is still exposed by legacy infrastructure docs and Makefile targets.
