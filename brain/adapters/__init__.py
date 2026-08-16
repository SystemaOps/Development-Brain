"""Adapters: implementations of the brain's ports.

Adapters may depend on ports and provider SDKs; the domain and application
layers never import this package.
"""

from brain.adapters.code_intelligence import PythonAstParser
from brain.adapters.embeddings import HashEmbeddingService
from brain.adapters.executors import FakeExecutor, PiExecutor
from brain.adapters.in_memory.executor_registry import InMemoryExecutorRegistry
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
    "DeploymentTopologyDetector",
    "DerivedSoftwareCatalog",
    "DeterministicCommandRunner",
    "FakeCommandRunner",
    "FakeExecutor",
    "FakePullRequestAdapter",
    "HashEmbeddingService",
    "InMemoryExecutorRegistry",
    "JiraAdapter",
    "ManifestTopologyDetector",
    "OpenProjectAdapter",
    "PiExecutor",
    "PythonAstParser",
    "ResourceDetector",
    "TopologyDiscoverer",
]
