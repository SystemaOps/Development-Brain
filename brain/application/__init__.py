"""Application services.

Application services orchestrate the domain model through ports.  They never
import adapters or provider SDKs: every dependency is an interface from
``brain.ports``, so the same services run against the in-memory reference
adapters and against PostgreSQL alike.
"""

from brain.application.code_intelligence import CodeIndexResult, CodeIntelligenceService
from brain.application.document_ingestion import (
    DocumentIngestionResult,
    DocumentIngestionService,
)
from brain.application.events import IncomingEventProcessor, ProcessOutcome
from brain.application.graph_integrity import (
    GraphIntegrityChecker,
    GraphIntegrityReport,
    IntegrityIssue,
)
from brain.application.graph_projection import GraphProjectionResult, GraphProjectionService
from brain.application.impact_analysis import ImpactAnalysis, ImpactAnalysisService
from brain.application.projections import CanonicalStateProjection
from brain.application.revisions import IncrementalRevisionHandler
from brain.application.topology import TopologyDiscoveryResult, TopologyDiscoveryService

__all__ = [
    "CanonicalStateProjection",
    "CodeIndexResult",
    "CodeIntelligenceService",
    "DocumentIngestionResult",
    "DocumentIngestionService",
    "GraphIntegrityChecker",
    "GraphIntegrityReport",
    "GraphProjectionResult",
    "GraphProjectionService",
    "ImpactAnalysis",
    "ImpactAnalysisService",
    "IncomingEventProcessor",
    "IncrementalRevisionHandler",
    "IntegrityIssue",
    "ProcessOutcome",
    "TopologyDiscoveryResult",
    "TopologyDiscoveryService",
]
