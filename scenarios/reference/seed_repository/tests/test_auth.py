"""Auth tests: related tests for the login service (FR-2)."""

from __future__ import annotations

import pytest

from ..src.auth.security import SecurityPolicy
from ..src.auth.service import AuthService
from ..src.users.user_model import AuthenticationError, User, UserRepository


@pytest.fixture
def auth() -> AuthService:
    users = UserRepository()
    users.add(User("alice", "secret"))
    return AuthService(users)


def test_login_returns_user(auth: AuthService) -> None:
    user = auth.login("alice", "secret")
    assert user.uid == "alice"


def test_login_wrong_password_records_failure(auth: AuthService) -> None:
    with pytest.raises(AuthenticationError):
        auth.login("alice", "wrong")
    assert auth.failed_attempts("alice") == 1


def test_five_failures_should_lock_account(auth: AuthService) -> None:
    """AC-1: a fifth failed attempt locks the account (not implemented yet)."""
    with pytest.raises(AuthenticationError):
        for _ in range(SecurityPolicy.MAX_FAILED_ATTEMPTS):
            auth.login("alice", "wrong")
