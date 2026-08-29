"""Domain unit tests for the canonical software model."""

from __future__ import annotations

from brain.domain.knowledge import DiscoveryMethod, KnowledgeEvidence, KnowledgeOrigin
from brain.domain.projects import Project
from brain.domain.software_model import (
    ComponentType,
    Interface,
    InterfaceType,
    Resource,
    ResourceType,
    SoftwareComponent,
    SoftwareDomain,
    System,
)


def test_domain_system_component_hierarchy() -> None:
    project = Project(name="ecommerce")
    domain = SoftwareDomain(project_id=project.id, name="Commerce")
    system = System(project_id=project.id, domain_id=domain.id, name="Checkout")
    component = SoftwareComponent(
        project_id=project.id,
        name="payment-service",
        component_type=ComponentType.BACKEND_SERVICE,
    )
    assert system.domain_id == domain.id
    assert component.component_type == ComponentType.BACKEND_SERVICE


def test_component_provenance() -> None:
    project = Project(name="auth")
    component = SoftwareComponent(
        project_id=project.id,
        name="auth-service",
        provenance=[
            KnowledgeEvidence(
                source_type="docker-compose",
                discovery_method=DiscoveryMethod.MANIFEST_ANALYSIS,
                origin=KnowledgeOrigin.DISCOVERED,
            )
        ],
    )
    assert component.provenance[0].origin == KnowledgeOrigin.DISCOVERED


def test_interface_belongs_to_component() -> None:
    project = Project(name="auth")
    component = SoftwareComponent(project_id=project.id, name="auth-service")
    interface = Interface(
        component_id=component.id,
        type=InterfaceType.REST,
        name="login API",
        schema_ref="openapi.yaml",
    )
    assert interface.component_id == component.id
    assert interface.schema_ref == "openapi.yaml"


def test_resource_types() -> None:
    project = Project(name="auth")
    assert Resource(project_id=project.id, name="primary-db", resource_type=ResourceType.POSTGRESQL)
    assert Resource(project_id=project.id, name="cache", resource_type=ResourceType.REDIS)
    assert Resource(project_id=project.id, name="events", resource_type=ResourceType.KAFKA)


def test_software_model_serializes() -> None:
    project = Project(name="auth")
    component = SoftwareComponent(project_id=project.id, name="auth-service")
    assert SoftwareComponent.model_validate_json(component.model_dump_json()) == component
