# Coding Agent Full Infrastructure

This is a complete MVP infrastructure for your coding-agent idea.

It includes:

| Service | Purpose | Host URL / Port |
|---|---|---|
| OpenProject | Human-agent project planning and approval UI | http://localhost:8081 |
| PostgreSQL | Agent app state + OpenProject database | localhost:5432 |
| Redis | Webhook/job queue | localhost:6379 |
| Neo4j | Code graph + project graph + memory graph | http://localhost:7474 |
| Weaviate | Vector database | http://localhost:8080 |
| llama.cpp | Optional local LLM server | http://localhost:8082 |
| agent-webhook | Receives OpenProject webhooks | http://localhost:8090 |
| agent-worker | Claims queued webhook jobs and delegates to planning-agent-core | internal |
| openproject-provision | One-time zero-manual OpenProject provisioning | internal |

## What is zero-manual here?

When you run Docker Compose, the provisioner automatically creates:

```text
coding-agent-bot user
admin permissions for the bot
OpenProject API token for the bot
OpenProject webhook pointing to agent-webhook
optional starter OpenProject project
optional starter project modules, work package types, and repository binding metadata
```

The API token is saved in a Docker volume and mounted read-only into planning-agent-core:

```text
/agent-secrets/openproject_api_token
```

The provisioner also writes a discovery report to the same Docker volume:

```text
/agent-secrets/openproject_provisioning.json
```

That report records discovered OpenProject IDs for required work package types, semantic statuses, priorities, recommended agent custom fields, webhook configuration, bot role/permission setup, starter-project work package type enablement, and optional starter project binding. It is intentionally name-based; the agent code should not assume numeric OpenProject IDs.

So you do **not** need to manually create a bot user, API token, or webhook in the OpenProject UI.

## OpenProject provisioning controls

The following environment variables tune discovery and optional setup:

```env
OP_REQUIRED_WORK_PACKAGE_TYPES=Epic,Story,Task
OP_SEMANTIC_STATUS_NAMES=Draft,Needs clarification,Awaiting approval,Ready,In progress,Blocked,Ready for verification,Changes required,Verified,Done,Cancelled
OP_REQUIRED_PRIORITIES=Low,Normal,High,Urgent,Immediate
OP_REQUIRED_PROJECT_MODULES=work_package_tracking,wiki,repository
OP_ENSURE_AGENT_CUSTOM_FIELDS=false
OP_AGENT_ROLE_NAME=Coding Agent
OP_AGENT_ROLE_PERMISSIONS=view_work_packages,add_work_packages,edit_work_packages,add_work_package_notes,view_project
OP_STARTER_REPOSITORY_KEY=sample-project
OP_STARTER_REPOSITORY_PATH=/workspace/repositories/sample_project
```

By default, custom fields are discovered and reported but not created. Set `OP_ENSURE_AGENT_CUSTOM_FIELDS=true` only after confirming the OpenProject version supports the desired work-package custom field format and assignment model.

## Start

```bash
cp .env.example .env
mkdir -p models workspace
docker compose up -d --build
```

Or with Make:

```bash
make setup
make up
```

Watch the important logs:

```bash
docker compose logs -f openproject-provision agent-webhook agent-worker
```

OpenProject:

```text
http://localhost:8081
```

Neo4j:

```text
http://localhost:7474
```

Weaviate:

```text
http://localhost:8080
```

## Start llama.cpp

Put a GGUF model in:

```text
./models/
```

Edit `.env`:

```env
LLAMA_MODEL_FILE=your-model.gguf
```

Start with the LLM profile:

```bash
docker compose --profile llm up -d --build
```

## OpenProject workflow idea

Use OpenProject work packages as the human-agent control surface:

```text
Epic / Feature / Task
        |
User reviews plan and comments
        |
User comments or updates a work package
        |
Webhook fires
        |
agent-worker claims the queued event
        |
planning-agent-core orchestrates workflow resume
```

The worker delegates to planning-agent-core through:

```text
POST /v1/events/{event_id}/orchestrate
```

## Where to plug in the real coding agent

The active implementation point is now the core workflow layer under:

```text
agent_core/agent_core/workflow/
agent_core/agent_core/application/
```

`infra/agent_trigger/app/agent_bridge.py` is legacy reference code and is no longer called by `agent-worker`.

The real coding-agent workflow should eventually:

```text
sync OpenProject work package/comments into Neo4j
embed descriptions/comments/decisions into Weaviate
create a git branch
use Tree-sitter/LSP/code graph context
implement the task
run tests
post progress/results back to OpenProject
```

## Webhook flow

```text
OpenProject comment/status update
        |
agent-webhook FastAPI service
        |
PostgreSQL pm_webhook_events table
        |
Redis queue
        |
agent-worker
        |
planning-agent-core /v1/events/{event_id}/orchestrate
        |
planning workflow resumes or records a context-sync-only decision
```

## Test webhook receiver manually

This tests the receiver/queue path. Full event orchestration is handled by planning-agent-core.

```bash
make test-webhook
```

## Show generated bot API token

```bash
make show-token
```

## Important security notes

For MVP, the bot is created as admin:

```env
OP_AGENT_ADMIN=true
```

This gives the agent broad control so it can create and maintain projects.

For production, change this design later:

```text
OP_AGENT_ADMIN=false
create a dedicated global/project role
grant only required permissions
store secrets in Vault/Kubernetes secrets/Docker secrets
use HTTPS
restrict webhook network access
```

## Reset everything

```bash
docker compose down -v
```

This deletes all persistent data.


## Fix included in this version

This fixed package uses `SECRET_KEY_BASE` for the OpenProject Docker container and generates a real random value during setup.

OpenProject 17.3.2+ refuses to boot with a missing/default/weak `SECRET_KEY_BASE`, so do not only copy `.env.example`.
Run:

```bash
make setup
```

or:

```bash
python scripts/generate_env.py
```

If the provisioner fails, it now prints the real Rails error and stops after 5 minutes instead of waiting forever.


## Troubleshooting: bot password validation

OpenProject requires generated user passwords to contain lowercase, uppercase, numeric, and special characters.

This package generates the `coding-agent-bot` password using:

```ruby
generate_policy_compliant_password(64)
```

If you still see this error:

```text
Validation failed: Password Must include characters of the following types...
```

run a clean retry:

```bash
docker compose down -v --remove-orphans
make setup
make up
make logs
```
