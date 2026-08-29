"""Weaviate connection configuration.

Settings are read from environment variables with sensible local-development
defaults so the adapter works out of the box against the ``compose.yaml``
service while remaining overridable for tests and containers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WeaviateSettings:
    """Immutable settings used to connect to Weaviate."""

    host: str = "localhost"
    port: int = 8080
    grpc_port: int = 50051
    scheme: str = "http"
    class_name: str = "SemanticRecord"

    @classmethod
    def from_env(cls) -> WeaviateSettings:
        """Build settings from ``BRAIN_WEAVIATE_*`` environment variables."""
        return cls(
            host=os.getenv("BRAIN_WEAVIATE_HOST", cls.host),
            port=int(os.getenv("BRAIN_WEAVIATE_PORT", str(cls.port))),
            grpc_port=int(os.getenv("BRAIN_WEAVIATE_GRPC_PORT", str(cls.grpc_port))),
            scheme=os.getenv("BRAIN_WEAVIATE_SCHEME", cls.scheme),
            class_name=os.getenv("BRAIN_WEAVIATE_CLASS", cls.class_name),
        )
