"""Application version metadata (Phase 31).

Exposes the package version and an optional Git build SHA.  The build SHA is
read from the ``BRAIN_BUILD_SHA`` environment variable (or the installed
``brain.VERSION`` constant); it is never guessed at import time.
"""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version


def package_version() -> str:
    """The installed package version (``brain`` distribution)."""
    try:
        return _pkg_version("brain")
    except PackageNotFoundError:
        return "0.1.0"


def build_sha() -> str | None:
    """Optional Git build SHA from ``BRAIN_BUILD_SHA``."""
    return os.getenv("BRAIN_BUILD_SHA") or None


def application_version() -> dict[str, str | None]:
    """Version metadata exposed by ``/api/v1/system/version``."""
    return {
        "version": package_version(),
        "build": build_sha() or "dev",
    }


__all__ = ["application_version", "build_sha", "package_version"]
