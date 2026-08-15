"""Verification adapters (Phase 13).

Deterministic command runner (real + fake), fake PR adapter, and the
in-memory verification run repository live here; all implement ports.
"""

from brain.adapters.verification.command_runner import (
    DeterministicCommandRunner,
    FakeCommandRunner,
)
from brain.adapters.verification.fake_pr import FakePullRequestAdapter

__all__ = [
    "DeterministicCommandRunner",
    "FakeCommandRunner",
    "FakePullRequestAdapter",
]
