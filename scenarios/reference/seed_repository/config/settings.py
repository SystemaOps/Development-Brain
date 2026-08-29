"""Runtime configuration for the login service."""

from __future__ import annotations


class Settings:
    """Static configuration; lockout policy lives in auth.security."""

    APP_NAME = "e2e-demo"
    MAX_LOGIN_ATTEMPTS = 5
