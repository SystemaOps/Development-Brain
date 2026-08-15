"""Application services.

Application services orchestrate the domain model through ports.  They never
import adapters or provider SDKs: every dependency is an interface from
``brain.ports``, so the same services run against the in-memory reference
adapters and against PostgreSQL alike.
"""

from brain.application.events import IncomingEventProcessor, ProcessOutcome
from brain.application.projections import CanonicalStateProjection
from brain.application.revisions import IncrementalRevisionHandler

__all__ = [
    "CanonicalStateProjection",
    "IncomingEventProcessor",
    "IncrementalRevisionHandler",
    "ProcessOutcome",
]
