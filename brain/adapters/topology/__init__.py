"""Topology discovery adapters (Phase 6).

Concrete implementations of the discovery pipeline: manifest, deployment, API
and resource detectors plus the composite discoverer that implements the
:class:`~brain.ports.topology.TopologyDiscoveryPort` contract.
"""

from brain.adapters.topology.api import ApiInterfaceDetector
from brain.adapters.topology.catalog import DerivedSoftwareCatalog
from brain.adapters.topology.deployment import DeploymentTopologyDetector
from brain.adapters.topology.discovery import TopologyDiscoverer
from brain.adapters.topology.manifest import ManifestTopologyDetector
from brain.adapters.topology.resources import ResourceDetector

__all__ = [
    "ApiInterfaceDetector",
    "DeploymentTopologyDetector",
    "DerivedSoftwareCatalog",
    "ManifestTopologyDetector",
    "ResourceDetector",
    "TopologyDiscoverer",
]
