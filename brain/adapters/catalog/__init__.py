"""Catalog adapters (Phase 15).

Backstage is an optional enrichment source behind ``SoftwareCatalogPort``;
the brain's derived catalog (from discovered topology) is the default.
"""

from brain.adapters.catalog.backstage import (
    BackstageCatalogAdapter,
    BackstageTransport,
)

__all__ = ["BackstageCatalogAdapter", "BackstageTransport"]
