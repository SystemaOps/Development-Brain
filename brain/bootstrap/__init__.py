"""Runtime composition root (Phases 21+).

``brain.bootstrap`` is the runtime-facing layer that turns the library into an
operable application.  It is intentionally separate from domain / ports /
application / adapters: only API, worker, scheduler, and CLI code import it,
and it may touch provider SDKs (FastAPI, Redis, ...) that core layers must
never see.
"""
