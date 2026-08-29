"""Security policy: lockout constants centralized (ADR-0001)."""

from __future__ import annotations


class SecurityPolicy:
    """Lockout policy constants for the login service (FR-1)."""

    MAX_FAILED_ATTEMPTS = 5
    LOCKOUT_DURATION_MINUTES = 15
