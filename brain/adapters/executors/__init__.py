"""Executor adapters (Phase 12).

Deterministic fake executor for tests, plus a Pi adapter that talks to a Pi
process over a JSONL/RPC protocol.  Both implement the :class:`ExecutorPort`
contract; the core never sees Pi session types.
"""

from brain.adapters.executors.fake import FakeExecutor
from brain.adapters.executors.pi import PiExecutor

__all__ = ["FakeExecutor", "PiExecutor"]
