"""Brain worker runtime (Phase 25).

Consumes canonical commands from the queue and invokes application services
through the same composition root as the API.  The worker never places
business logic in the dispatcher; failures are persisted through the command
failure repository and never crash the process.
"""
