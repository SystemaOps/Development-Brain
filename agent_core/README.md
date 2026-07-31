# Planning Agent Core

This is the fuller project scaffold for the planning agent.

Core concept preserved from the start:

```text
User request / README / project idea
        ↓
Document ingestion
        ↓
Chunking + structured extraction
        ↓
Clarification questions if unclear
        ↓
Versioned plan:
Vision → Capability → Epic → Story → Task
        ↓
PostgreSQL source of truth
        ↓
OpenProject artifacts
        ↓
Neo4j relationship memory
        ↓
Weaviate semantic memory
        ↓
Context capsules for future coding agents
```

## Design rule

```text
PostgreSQL = source of truth
Neo4j      = relationship intelligence
Weaviate   = semantic retrieval
OpenProject = human-facing work management
```

## Run

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d postgres neo4j weaviate
pip install -e ".[dev]"
uvicorn agent_core.main:app --reload
```

## Main routes

```text
GET  /health

POST /v1/projects
GET  /v1/projects/{project_key}

POST /v1/documents/upload?project_key=coding-agent
GET  /v1/documents/{document_id}/chunks

POST /v1/planning/sessions
GET  /v1/planning/sessions/{session_id}
POST /v1/planning/sessions/{session_id}/answers
POST /v1/planning/sessions/{session_id}/draft-plan
POST /v1/planning/plan-versions/{plan_version_id}/approve

POST /v1/context/plan-nodes/{plan_node_id}/capsule

POST /v1/provisioning/projects/{project_key}
```

## Important files

```text
docs/postgres_schema.sql       Full PostgreSQL schema
docs/neo4j_schema.cypher       Neo4j constraints and projection model
docs/weaviate_schema.md        Weaviate collections
agent_core/models.py  SQLAlchemy implementation for core tables
agent_core/services/  Business logic
agent_core/adapters/  OpenProject, Neo4j, Weaviate adapters
```

## MVP status

This is a serious MVP scaffold. It includes complete schemas and working API routes for project creation, document upload/chunking, planning sessions, question answering, plan drafting, approval, context capsule generation, and provisioning job creation.

The LLM and external systems are integration points. The code includes safe deterministic fallback planning when the local LLM endpoint is unavailable.


## To start planning with a document as input, you would call:

POST /v1/planning/sessions

## This is the main endpoint that initiates a planning session. Here's how to use it:

Request Format:
```
 HTTP
POST /v1/planning/sessions
Content-Type: application/json
JSON
{
  "project_key": "your-project-key",
  "input_mode": "document",
  "original_request": "Your planning request or goal",
  "intake": {
    "document_id": "uuid-of-the-uploaded-document"
  }
} 
```

Step-by-step process:
First, upload your document using:
```
HTTP
POST /v1/documents/upload?project_key=your-project-key
Then, start a planning session with:

HTTP
POST /v1/planning/sessions
Optionally, if clarification questions arise, answer them with:

HTTP
POST /v1/planning/sessions/{session_id}/answers
Finally, draft the plan:

HTTP
POST /v1/planning/sessions/{session_id}/draft-plan
Example using curl:
```
# Start planning session with document
```
curl -X POST "http://localhost:8000/v1/planning/sessions" \
  -H "Content-Type: application/json" \
  -d '{
    "project_key": "coding-agent",
    "input_mode": "document",
    "original_request": "Create a web application for managing tasks",
    "intake": {
      "document_id": "123e4567-e89b-12d3-a456-426614174000"
    }
  }'
```
The system will automatically process your document and generate a plan based on the content, following the hierarchical structure (Vision → Capability → Epic → Story → Task) as defined in the planner system prompt.