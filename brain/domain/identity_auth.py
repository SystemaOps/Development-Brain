"""API authentication (Task 40.1).

Separate identities are recognized at the API edge:

- HUMAN:      a person using the control plane
- SERVICE:    an internal service account (automation, scheduler, CLI)
- WEBHOOK:    an external provider delivering events
- EXECUTOR:   a coding executor fetching context/tools
- ADMIN:      full control (seeding, capability refresh)

Credentials are API keys: only their SHA-256 hashes are ever stored; plain
keys exist once at provisioning time.  Keys are seeded from the environment
(``BRAIN_API_KEYS_*``) at container startup; runtime-provisioned keys store
only the hash.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class IdentityRole(StrEnum):
    HUMAN = "human"
    SERVICE = "service"
    WEBHOOK = "webhook"
    EXECUTOR = "executor"
    ADMIN = "admin"


class Identity(BaseModel):
    """The authenticated caller at the API edge."""

    name: str
    role: IdentityRole
    key_id: uuid.UUID | None = None


class ApiKey(BaseModel):
    """One API key (hash-only persisted representation)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    role: IdentityRole
    key_hash: str
    enabled: bool = True


def hash_api_key(api_key: str) -> str:
    """SHA-256 of the key; the plaintext is never stored or logged."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def generate_api_key() -> tuple[str, ApiKey]:
    """Create a plaintext key + its hash-only record.

    Returns ``(plaintext, record)``; the plaintext is returned exactly once.
    """
    plaintext = f"brain_{secrets.token_urlsafe(32)}"
    record = ApiKey(name="", role=IdentityRole.SERVICE, key_hash=hash_api_key(plaintext))
    return plaintext, record


__all__ = [
    "ApiKey",
    "Identity",
    "IdentityRole",
    "constant_time_equal",
    "generate_api_key",
    "hash_api_key",
]
