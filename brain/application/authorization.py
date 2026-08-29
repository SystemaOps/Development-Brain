"""Authorization service (Task 40.2).

Decides whether an identity may perform an operation.  Policy coverage:

- PROJECT_ACCESS:      read/create/update project and repository data
- EXECUTION_TRIGGER:   start/retry executions and run work items
- OBSERVATION_RESOLVE: acknowledge/resolve observations
- PR_CREATE:           create pull/merge requests
- ADMIN:               admin operations (capability refresh, seeding)

ADMIN may do everything; WEBHOOK identities may only deliver events;
EXECUTOR identities may only access context/retrieval.
"""

from __future__ import annotations

from enum import StrEnum

from brain.domain.identity_auth import Identity, IdentityRole


class Permission(StrEnum):
    PROJECT_ACCESS = "project_access"
    EXECUTION_TRIGGER = "execution_trigger"
    OBSERVATION_RESOLVE = "observation_resolve"
    PR_CREATE = "pr_create"
    ADMIN = "admin"
    WEBHOOK_DELIVERY = "webhook_delivery"
    EXECUTOR_CONTEXT = "executor_context"


_ROLE_PERMISSIONS: dict[IdentityRole, frozenset[Permission]] = {
    IdentityRole.ADMIN: frozenset(Permission),
    IdentityRole.HUMAN: frozenset(
        {
            Permission.PROJECT_ACCESS,
            Permission.EXECUTION_TRIGGER,
            Permission.OBSERVATION_RESOLVE,
            Permission.PR_CREATE,
        }
    ),
    IdentityRole.SERVICE: frozenset(
        {
            Permission.PROJECT_ACCESS,
            Permission.EXECUTION_TRIGGER,
            Permission.OBSERVATION_RESOLVE,
            Permission.PR_CREATE,
        }
    ),
    IdentityRole.WEBHOOK: frozenset({Permission.WEBHOOK_DELIVERY}),
    IdentityRole.EXECUTOR: frozenset({Permission.EXECUTOR_CONTEXT}),
}


class AuthorizationError(PermissionError):
    """Raised when an identity is not permitted to perform an operation."""


class AuthorizationService:
    """Evaluates identity -> permission grants."""

    def allow(self, identity: Identity, permission: Permission) -> None:
        if permission not in _ROLE_PERMISSIONS.get(identity.role, frozenset()):
            raise AuthorizationError(
                f"{identity.role.value} identity '{identity.name}' is not "
                f"permitted: {permission.value}"
            )

    def may(self, identity: Identity, permission: Permission) -> bool:
        return permission in _ROLE_PERMISSIONS.get(identity.role, frozenset())


__all__ = ["AuthorizationError", "AuthorizationService", "Permission"]
