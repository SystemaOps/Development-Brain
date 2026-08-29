"""Application services.

Application services orchestrate the domain model through ports.  They never
import adapters or provider SDKs: every dependency is an interface from
``brain.ports``, so the same services run against the in-memory reference
adapters and against PostgreSQL alike.
"""

from brain.application.approval_gate import ApprovalGate
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
from brain.application.documentation_catalog_sync import (
    CatalogConflict,
    CatalogReconciliationResult,
    DocumentationCatalogSyncService,
    DocumentSyncResult,
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
from brain.application.human_feedback import HumanFeedbackService
from brain.application.hybrid_retrieval import HybridRetrievalService, RetrievalCandidate
from brain.application.impact_analysis import ImpactAnalysis, ImpactAnalysisService
from brain.application.jit_retrieval import JustInTimeRetrieval
from brain.application.lexical_search import LexicalSearchService, tokenize
from brain.application.observability import (
    ContextMetricsBuilder,
    ContextOutcomeEvaluator,
    MetricsCollector,
    MetricsReporter,
    ObservabilityService,
    StructuredLogger,
)
from brain.application.observation_projection import ObservationProjectionService
from brain.application.observations import ObservationPolicy, ObservationService
from brain.application.optimization import (
    BanditRouter,
    ContextRankingFeedbackService,
    ExecutorQualityTracker,
    ModelRouter,
    TaskComplexityService,
    TestSelectionOptimizer,
)
from brain.application.planning import PlanningResult, PlanningService
from brain.application.policy_service import PolicyEvaluation, PolicyService, RiskAssessment
from brain.application.projections import CanonicalStateProjection
from brain.application.revisions import IncrementalRevisionHandler
from brain.application.runtime import (
    AdvancedTestSelector,
    CoverageImporter,
    OtelTraceImporter,
    RuntimeEvidenceIngester,
    RuntimeReconciler,
)
from brain.application.semantic_indexing import IndexingResult, SemanticIndexingService
from brain.application.token_estimation import TokenEstimator
from brain.application.topology import TopologyDiscoveryResult, TopologyDiscoveryService
from brain.application.verification_engine import VerificationEngine, VerificationOutcome
from brain.application.work_management_sync import (
    SyncResult,
    WebhookNormalizationResult,
    WorkManagementSyncService,
)
from brain.application.workflow_engine import RetryDecision, WorkflowEngine, WorkflowOutcome
from brain.application.workspace_manager import Workspace, WorkspaceManager

__all__ = [
    "TOOL_REGISTRY",
    "ApprovalGate",
    "AdvancedTestSelector",
    "BanditRouter",
    "BrainTools",
    "BudgetAllocator",
    "BuildResult",
    "BuiltExecution",
    "CanonicalStateProjection",
    "CatalogConflict",
    "CatalogReconciliationResult",
    "CodeIndexResult",
    "CodeIntelligenceService",
    "ContextEngineService",
    "ContextMetricsBuilder",
    "ContextOutcomeEvaluator",
    "ContextRanker",
    "ContextRankingFeedbackService",
    "CoverageImporter",
    "DocumentationCatalogSyncService",
    "DocumentIngestionResult",
    "DocumentIngestionService",
    "DocumentSyncResult",
    "ExecutionRequestBuilder",
    "ExecutorQualityTracker",
    "GraphIntegrityChecker",
    "GraphIntegrityReport",
    "GraphProjectionResult",
    "GraphProjectionService",
    "HumanFeedbackService",
    "HybridRetrievalService",
    "ImpactAnalysis",
    "ImpactAnalysisService",
    "IncomingEventProcessor",
    "IncrementalRevisionHandler",
    "IndexingResult",
    "IntegrityIssue",
    "JustInTimeRetrieval",
    "LexicalSearchService",
    "MetricsCollector",
    "MetricsReporter",
    "ModelRouter",
    "ObservationPolicy",
    "ObservationProjectionService",
    "ObservationService",
    "ObservabilityService",
    "OtelTraceImporter",
    "ProcessOutcome",
    "PlanningResult",
    "PlanningService",
    "PolicyEvaluation",
    "PolicyService",
    "RetrievalCandidate",
    "RetryDecision",
    "RiskAssessment",
    "RuntimeEvidenceIngester",
    "RuntimeReconciler",
    "SemanticIndexingService",
    "StructuredLogger",
    "SyncResult",
    "TaskComplexityService",
    "TestSelectionOptimizer",
    "TokenEstimator",
    "TopologyDiscoveryResult",
    "TopologyDiscoveryService",
    "VerificationEngine",
    "VerificationOutcome",
    "WebhookNormalizationResult",
    "WorkflowEngine",
    "WorkflowOutcome",
    "WorkManagementSyncService",
    "Workspace",
    "WorkspaceManager",
    "tokenize",
]
