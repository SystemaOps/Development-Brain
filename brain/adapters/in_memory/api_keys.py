"""API key store (Task 40.1).

Stores only key hashes.  Seed keys are provisioned from the environment at
startup; additional keys can be provisioned at runtime (hash-only).
"""

from __future__ import annotations

import uuid
from typing import Protocol

from brain.domain.identity_auth import ApiKey, IdentityRole, hash_api_key


class ApiKeyStore(Protocol):
    async def save(self, key: ApiKey) -> ApiKey: ...

    async def get_by_id(self, key_id: uuid.UUID) -> ApiKey | None: ...

    async def list(self) -> list[ApiKey]: ...

    async def authenticate(self, plaintext: str) -> ApiKey | None:
        """Return the key record for a plaintext key, if valid."""
        ...


class InMemoryApiKeyStore:
    """In-memory reference implementation."""

    def __init__(self) -> None:
        self._keys: dict[uuid.UUID, ApiKey] = {}

    async def save(self, key: ApiKey) -> ApiKey:
        self._keys[key.id] = key
        return key

    async def get_by_id(self, key_id: uuid.UUID) -> ApiKey | None:
        return self._keys.get(key_id)

    async def list(self) -> list[ApiKey]:
        return list(self._keys.values())

    async def authenticate(self, plaintext: str) -> ApiKey | None:
        wanted = hash_api_key(plaintext)
        for key in self._keys.values():
            if key.enabled and key.key_hash == wanted:
                return key
        return None


async def seed_keys_from_env(store: ApiKeyStore, raw: str) -> int:
    """Provision ``BRAIN_API_KEYS`` entries: ``name=role:plaintext[;...]``."""
    count = 0
    for entry in [part for part in raw.split(";") if part.strip()]:
        name, _, credential = entry.partition("=")
        role_name, _, plaintext = credential.partition(":")
        if not plaintext.strip():
            continue
        key = ApiKey(
            name=name.strip(),
            role=IdentityRole(role_name.strip()),
            key_hash=hash_api_key(plaintext.strip()),
        )
        await store.save(key)
        count += 1
    return count


__all__ = ["ApiKeyStore", "InMemoryApiKeyStore", "seed_keys_from_env"]
