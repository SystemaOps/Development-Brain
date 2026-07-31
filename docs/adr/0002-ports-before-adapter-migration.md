# ADR 0002: Introduce Ports Before Adapter Migration

## Status

Accepted

## Context

The repository already contains concrete integrations for OpenProject, Neo4j, Weaviate, PostgreSQL, Redis, LangGraph, and an OpenAI-compatible LLM endpoint. Some implementations are duplicated between `agent_core` and `infra/agent_trigger`.

## Decision

Introduce technology-independent ports before moving or replacing concrete implementations. Application services and workflow nodes should depend on ports and typed contracts, while adapters implement those contracts.

## Consequences

- Existing working integrations can be wrapped instead of rewritten.
- Duplicate implementations can converge behind one contract.
- Domain and skill-contract modules must not import vendor clients or framework code.
- More interface code will exist temporarily during migration.
