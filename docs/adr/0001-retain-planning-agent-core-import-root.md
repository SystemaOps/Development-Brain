# ADR 0001: Retain `agent_core` Import Root

## Status

Accepted

## Context

The README describes a system that will eventually contain planning, coding, and verification agents. The existing newer implementation already uses the Python package and distribution name `agent_core`. Renaming it now would add import churn before stable boundaries, tests, and migrations exist.

## Decision

Keep the package and import root `agent_core` for the initial migration. Add subpackages for domain, ports, adapters, workflows, agents, and policies under that root.

## Consequences

- Existing imports can continue to work while refactoring proceeds.
- Documentation must explain that the package now contains more than only planning behavior.
- A future package rename can be considered after the architecture stabilizes and compatibility shims are easy to maintain.
