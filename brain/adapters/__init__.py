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

__all__ = [
    "ApiInterfaceDetector",
    "DeploymentTopologyDetector",
    "DerivedSoftwareCatalog",
    "FakeExecutor",
    "HashEmbeddingService",
    "InMemoryExecutorRegistry",
    "ManifestTopologyDetector",
    "PiExecutor",
    "PythonAstParser",
    "ResourceDetector",
    "TopologyDiscoverer",
]
