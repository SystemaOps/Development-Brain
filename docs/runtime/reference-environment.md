# Full Reference End-to-End Environment (Phase 39)

The reference environment proves the complete architecture as an observable,
recoverable system that visibly collaborates with humans.

## Start everything

```bash
docker compose \
  -f compose.yaml \
  -f compose.openproject.yaml \
  -f compose.xwiki.yaml \
  -f compose.docling.yaml \
  -f compose.backstage.yaml \
  -f compose.gitlab.yaml \
  up -d
```

This starts the Brain core plus all reference integrations (the later
overlays merge into the core exactly like any single-purpose overlay):

| Service       | URL                          | Purpose                                    |
| ------------- | ---------------------------- | ------------------------------------------ |
| Brain API     | http://localhost:8000        | control plane (`/api/v1/...`)              |
| OpenProject   | http://localhost:8081        | work management (webhook provider)         |
| XWiki         | http://localhost:8082        | knowledge base (optional documentation)    |
| Docling       | http://localhost:5001        | document conversion                        |
| Backstage     | http://localhost:7007        | optional software catalog                  |
| GitLab        | http://localhost:8929        | merge-request runtime                      |

Supporting stores: Postgres, Neo4j, Weaviate, Redis, MinIO (all healthchecked).

## Env templates

`deploy/env/` contains `.env.example` templates for each integration. The
compose overlays set the wiring automatically; credentials for OpenProject /
GitLab / XWiki must be created on first login:

- OpenProject: http://localhost:8081 (first-run admin setup)
- GitLab: http://localhost:8929 (root / `brain-secret-password`)
- XWiki: http://localhost:8082 (admin / `admin`)

## Seed the sample scenario

```bash
# 1. Register the sample repository + requirement + work item.
uv run python -m scenarios.reference.seed --project "e2e-demo"

# 2. Watch the worker consume the queued ingestion/execution commands.
docker compose -f compose.yaml logs -f brain-worker
```

The sample repository (`scenarios/reference/seed_repository/`) contains a
login service that already tracks failed attempts (so the Brain can discover
the partial implementation of account locking).

## Scripted scenario (deterministic CI)

`tests/test_phase39_reference_env.py` walks the full loop with controlled
adapters:

1. seed project/repository/requirement/work item (39.2/39.3)
2. partial implementation detected -> IMPLEMENTATION_STATUS observation +
   human-tool comment (39.4)
3. context quality: requirement/auth/user-model/security/tests included,
   unrelated module ranked last, budget respected (39.5)
4. execution -> verification FAIL (first attempt) -> retry -> PASS -> PR
   created -> observation projected (39.6/39.7/39.8)
5. merge + re-ingest: code graph at the merged revision + re-sync enqueued
   (39.9)
6. human feedback: HUMAN_ACTION_REQUIRED -> reply -> HumanFeedbackReceived ->
   context rebuilt -> workflow resumes (39.10)

## Overlay composition

```text
compose.yaml            (core)
compose.openproject.yaml
compose.xwiki.yaml
compose.docling.yaml
compose.backstage.yaml  (optional; may be dropped)
compose.gitlab.yaml
```

Every integration except the core is optional in the product; dropping an
overlay keeps the Brain fully functional with the corresponding capability
reported DISABLED/UNAVAILABLE.