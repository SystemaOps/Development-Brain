"""Composite topology discovery (Tasks 6.1 + 6.4).

Runs the manifest, deployment, API and resource detectors over a repository's
file contents and merges the results into one :class:`DiscoveredTopology`.
This is the pluggable ``TopologyDiscoveryPort`` implementation; detectors are
injected so the pipeline can grow (e.g. a Docling-based detector later).
"""

from __future__ import annotations

from brain.adapters.topology.api import ApiInterfaceDetector
from brain.adapters.topology.deployment import DeploymentTopologyDetector
from brain.adapters.topology.manifest import ManifestTopologyDetector
from brain.adapters.topology.resources import ResourceDetector
from brain.domain.identity import RepositoryId
from brain.domain.topology import DiscoveredTopology


class TopologyDiscoverer:
    """Default :class:`TopologyDiscoveryPort` implementation."""

    def __init__(
        self,
        manifest: ManifestTopologyDetector | None = None,
        deployment: DeploymentTopologyDetector | None = None,
        api: ApiInterfaceDetector | None = None,
        resources: ResourceDetector | None = None,
    ) -> None:
        self._manifest = manifest or ManifestTopologyDetector()
        self._deployment = deployment or DeploymentTopologyDetector()
        self._api = api or ApiInterfaceDetector()
        self._resources = resources or ResourceDetector()

    async def discover(
        self, repository_id: RepositoryId, revision: str, snapshot_files: dict[str, str]
    ) -> DiscoveredTopology:
        topology = DiscoveredTopology(repository_id=repository_id, revision=revision)

        manifest = self._manifest.detect(repository_id, revision, snapshot_files)
        topology.merge(manifest)

        deployment = self._deployment.detect(repository_id, revision, snapshot_files)
        topology.merge(deployment)

        component_names = [c.name for c in topology.components]
        api = self._api.detect(repository_id, revision, snapshot_files, component_names)
        topology.merge(api)

        resources = self._resources.detect(repository_id, revision, snapshot_files)
        topology.merge(resources)

        return topology


__all__ = ["TopologyDiscoverer"]
