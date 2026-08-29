"""Login flow with partial account-locking implementation.

Tracks failed attempts per account (FR-2) but does NOT enforce the lockout
after five failures (FR-1 / AC-1..AC-4 are not implemented).
"""

from __future__ import annotations

from ..users.user_model import (
    AuthenticationError,
    User,
    UserRepository,
)
from .security import SecurityPolicy


class AuthService:
    """Validates credentials and tracks failed attempts per account."""

    def __init__(
        self,
        users: UserRepository,
        *,
        policy: SecurityPolicy | None = None,
    ) -> None:
        self._users = users
        self._policy = policy or SecurityPolicy()
        self._failed_attempts: dict[str, int] = {}

    def login(self, uid: str, password: str) -> User:
        user = self._users.get(uid)
        if user is None or user.password != password:
            self._record_failure(uid)
            raise AuthenticationError(uid)
        self._failed_attempts.pop(uid, None)
        return user

    def failed_attempts(self, uid: str) -> int:
        return self._failed_attempts.get(uid, 0)

    def _record_failure(self, uid: str) -> None:
        # Partial implementation (FR-1): the counter exists but the lockout
        # after MAX_FAILED_ATTEMPTS is NOT enforced.
        self._failed_attempts[uid] = self.failed_attempts(uid) + 1
