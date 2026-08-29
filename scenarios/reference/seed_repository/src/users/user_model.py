"""User model and repository for the login service."""

from __future__ import annotations


class User:
    """A registered account."""

    def __init__(self, uid: str, password: str) -> None:
        self.uid = uid
        self.password = password


class AuthenticationError(Exception):
    """Raised when credentials are invalid (FR-2 / AC-6)."""

    def __init__(self, uid: str) -> None:
        super().__init__(f"authentication failed for {uid}")
        self.uid = uid


class UserRepository:
    """In-memory user store."""

    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    def add(self, user: User) -> None:
        self._users[user.uid] = user

    def get(self, uid: str) -> User | None:
        return self._users.get(uid)
