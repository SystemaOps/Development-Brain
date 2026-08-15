"""CI validation port.

Deterministic project-configured checks (tests, lint, build, type checks)
are run through this port so verification does not depend on one CI system.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.identity import RepositoryId


@runtime_checkable
class CIValidationPort(Protocol):
    async def run_validation(
        self, repository_id: RepositoryId, revision: str
    ) -> dict[str, object]: ...
