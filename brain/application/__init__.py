"""Application services.

Application services orchestrate the domain model through ports.  They never
import adapters or provider SDKs: every dependency is an interface from
``brain.ports``, so the same services run against the in-memory reference
adapters and against PostgreSQL alike.
"""

from brain.application.brain_tools import TOOL_REGISTRY, BrainTools
from brain.application.code_intelligence import CodeIndexResult, CodeIntelligenceService
from brain.application.context_engine import (
    BudgetAllocator,
    BuildResult,
    ContextEngineService,
    ContextRanker,
)
from brain.application.document_ingestion import (
    DocumentIngestionResult,
    DocumentIngestionService,
)
from brain.application.events import IncomingEventProcessor, ProcessOutcome
from brain.application.execution_request_builder import (
    BuiltExecution,
    ExecutionRequestBuilder,
)
from brain.application.graph_integrity import (
    GraphIntegrityChecker,
    GraphIntegrityReport,
    IntegrityIssue,
)
from brain.application.graph_projection import GraphProjectionResult, GraphProjectionService
from brain.application.hybrid_retrieval import HybridRetrievalService, RetrievalCandidate
from brain.application.impact_analysis import ImpactAnalysis, ImpactAnalysisService
from brain.application.jit_retrieval import JustInTimeRetrieval
from brain.application.lexical_search import LexicalSearchService, tokenize
from brain.application.planning import PlanningResult, PlanningService
from brain.application.projections import CanonicalStateProjection
from brain.application.revisions import IncrementalRevisionHandler
from brain.application.semantic_indexing import IndexingResult, SemanticIndexingService
from brain.application.token_estimation import TokenEstimator
from brain.application.topology import TopologyDiscoveryResult, TopologyDiscoveryService
from brain.application.verification_engine import VerificationEngine, VerificationOutcome
from brain.application.work_management_sync import (
    SyncResult,
    WebhookNormalizationResult,
    WorkManagementSyncService,
)
from brain.application.workspace_manager import Workspace, WorkspaceManager

__all__ = [
    "TOOL_REGISTRY",
    "BrainTools",
    "BudgetAllocator",
    "BuildResult",
    "BuiltExecution",
    "CanonicalStateProjection",
    "CodeIndexResult",
    "CodeIntelligenceService",
    "ContextEngineService",
    "ContextRanker",
    "DocumentIngestionResult",
    "DocumentIngestionService",
    "ExecutionRequestBuilder",
    "GraphIntegrityChecker",
    "GraphIntegrityReport",
    "GraphProjectionResult",
    "GraphProjectionService",
    "HybridRetrievalService",
    "ImpactAnalysis",
    "ImpactAnalysisService",
    "IncomingEventProcessor",
    "IncrementalRevisionHandler",
    "IndexingResult",
    "IntegrityIssue",
    "JustInTimeRetrieval",
    "LexicalSearchService",
    "ProcessOutcome",
    "PlanningResult",
    "PlanningService",
    "RetrievalCandidate",
    "SemanticIndexingService",
    "SyncResult",
    "TokenEstimator",
    "TopologyDiscoveryResult",
    "TopologyDiscoveryService",
    "VerificationEngine",
    "VerificationOutcome",
    "WebhookNormalizationResult",
    "WorkManagementSyncService",
    "Workspace",
    "WorkspaceManager",
    "tokenize",
]
