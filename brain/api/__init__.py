"""FastAPI control plane (Phases 23+).

Exposes the existing Brain application services through a provider-neutral
REST API.  ``brain.api`` is part of the runtime layer (like ``brain.bootstrap``);
it may use FastAPI/Starlette but must not leak provider types into the
application contracts.
"""
