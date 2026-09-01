"""FastAPI authentication dependencies (Task 40.1/40.3).

- :func:`api_key_dependency` validates ``Authorization: Bearer <key>`` or
  ``X-API-Key`` against the container's :class:`ApiKeyStore` and installs
  ``request.state.identity``.
- :func:`require_permission` enforces authorization on top of an identity.
- :func:`verify_webhook` validates provider signatures/tokens before a
  webhook payload is normalized (Task 40.3).
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from brain.api.dependencies import get_container
from brain.application.authorization import (
    AuthorizationError,
    AuthorizationService,
    Permission,
)
from brain.bootstrap.container import BrainContainer
from brain.domain.identity_auth import Identity, IdentityRole

_UNAUTHORIZED = status.HTTP_401_UNAUTHORIZED
_FORBIDDEN = status.HTTP_403_FORBIDDEN


def _extract_key(request: Request) -> str:
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header[len("bearer ") :].strip()
    return (request.headers.get("X-API-Key") or "").strip()


async def api_key_dependency(request: Request) -> Identity:
    container: BrainContainer = get_container(request)
    api_keys = container.services["api_key_store"]
    from brain.adapters.in_memory.api_keys import InMemoryApiKeyStore

    assert isinstance(api_keys, InMemoryApiKeyStore)
    raw_key = _extract_key(request)
    if not raw_key:
        raise HTTPException(status_code=_UNAUTHORIZED, detail="missing api key")
    key = await api_keys.authenticate(raw_key)
    if key is None:
        raise HTTPException(status_code=_UNAUTHORIZED, detail="invalid api key")
    identity = Identity(name=key.name, role=key.role, key_id=key.id)
    request.state.identity = identity
    return identity


def require_permission(permission: Permission) -> Callable[..., Awaitable[Identity]]:
    async def _dependency(
        request: Request,
        identity: Annotated[Identity, Depends(api_key_dependency)],
    ) -> Identity:
        service = AuthorizationService()
        try:
            service.allow(identity, permission)
        except AuthorizationError as exc:
            raise HTTPException(status_code=_FORBIDDEN, detail=str(exc)) from exc
        return identity

    return _dependency


def verify_webhook(provider: str) -> Callable[..., Awaitable[Request]]:
    """Validate the provider signature/token before normalization (40.3)."""

    async def _dependency(request: Request) -> Request:
        container: BrainContainer = get_container(request)
        security = container.settings.security
        if provider == "openproject":
            secret = security.webhook_openproject_secret
            if not secret:
                raise HTTPException(status_code=_UNAUTHORIZED, detail=f"webhook not configured {secret=}")
            signature = request.headers.get("X-OpenProject-Signature") or ""
            raw = await request.body()
            expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise HTTPException(status_code=_UNAUTHORIZED, detail="invalid signature")
        elif provider == "gitlab":
            token = security.webhook_gitlab_token
            if not token:
                raise HTTPException(status_code=_UNAUTHORIZED, detail="webhook not configured")
            supplied = request.headers.get("X-Gitlab-Token") or ""
            if not hmac.compare_digest(supplied, token):
                raise HTTPException(status_code=_UNAUTHORIZED, detail="invalid token")
        else:
            raise HTTPException(status_code=_UNAUTHORIZED, detail="unknown provider")
        request.state.identity = Identity(name=f"webhook:{provider}", role=IdentityRole.WEBHOOK)
        return request

    return _dependency


def identity_of(request: Request) -> Identity | None:
    return getattr(request.state, "identity", None)


__all__ = [
    "api_key_dependency",
    "identity_of",
    "require_permission",
    "verify_webhook",
]
