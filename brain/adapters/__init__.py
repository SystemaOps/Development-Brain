"""Adapters: implementations of the brain's ports.

Adapters may depend on ports and provider SDKs; the domain and application
layers never import this package.
"""

from brain.adapters.catalog.backstage import BackstageCatalogAdapter
from brain.adapters.catalog.derived import DerivedCatalogPortAdapter
from brain.adapters.code_intelligence import PythonAstParser
from brain.adapters.documentation import (
    GitMarkdownDocumentationAdapter,
    XWikiDocumentationAdapter,
)
from brain.adapters.embeddings import HashEmbeddingService
from brain.adapters.executors import FakeExecutor, PiExecutor
from brain.adapters.in_memory.executor_registry import InMemoryExecutorRegistry
from brain.adapters.in_memory.observability import InMemoryMetricsRepository
from brain.adapters.in_memory.policies import InMemoryApprovalRepository
from brain.adapters.topology import (
    ApiInterfaceDetector,
    DeploymentTopologyDetector,
    DerivedSoftwareCatalog,
    ManifestTopologyDetector,
    ResourceDetector,
    TopologyDiscoverer,
)
from brain.adapters.verification import (
    DeterministicCommandRunner,
    FakeCommandRunner,
    FakePullRequestAdapter,
)
from brain.adapters.work_management import (
    JiraAdapter,
    OpenProjectAdapter,
)

__all__ = [
    "ApiInterfaceDetector",
    "BackstageCatalogAdapter",
    "DeploymentTopologyDetector",
    "DerivedCatalogPortAdapter",
    "DerivedSoftwareCatalog",
    "DeterministicCommandRunner",
    "FakeCommandRunner",
    "FakeExecutor",
    "FakePullRequestAdapter",
    "GitMarkdownDocumentationAdapter",
    "HashEmbeddingService",
    "InMemoryApprovalRepository",
    "InMemoryExecutorRegistry",
    "InMemoryMetricsRepository",
    "JiraAdapter",
    "ManifestTopologyDetector",
    "OpenProjectAdapter",
    "PiExecutor",
    "PythonAstParser",
    "ResourceDetector",
    "TopologyDiscoverer",
    "XWikiDocumentationAdapter",
]
