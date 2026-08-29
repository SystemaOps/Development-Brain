"""Intentionally unrelated module: must be excluded from work-item context."""

from __future__ import annotations


class NotificationService:
    """Sends notifications; unrelated to authentication."""

    def send(self, recipient: str, message: str) -> None:
        raise NotImplementedError(recipient, message)
