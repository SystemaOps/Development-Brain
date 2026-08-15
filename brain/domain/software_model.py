"""Canonical software model: Domain, System, SoftwareComponent, Interface, Resource.

These entities must not depend on Backstage or any other catalog.  The brain
discovers them from repositories and reconciles declared metadata later.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ActorId, ProjectId, RepositoryId
from brain.domain.knowledge import KnowledgeEvidence


class SoftwareDomain(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: ProjectId
    name: str
    description: str | None = None
    system_ids: list[uuid.UUID] = Field(default_factory=list)
    external_refs: list[ExternalReference] = Field(default_factory=list)


class System(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: ProjectId
    domain_id: uuid.UUID | None = None
    name: str
    description: str | None = None
    component_ids: list[uuid.UUID] = Field(default_factory=list)
    external_refs: list[ExternalReference] = Field(default_factory=list)


class ComponentType(StrEnum):
    BACKEND_SERVICE = "backend_service"
    FRONTEND_APPLICATION = "frontend_application"
    LIBRARY = "library"
    WORKER = "worker"
    CLI = "cli"
    DATA_PIPELINE = "data_pipeline"
    EMBEDDED_FIRMWARE = "embedded_firmware"
    INFRASTRUCTURE_MODULE = "infrastructure_module"


class SoftwareComponent(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: ProjectId
    name: str
    component_type: ComponentType = ComponentType.LIBRARY
    repository_ids: list[RepositoryId] = Field(default_factory=list)
    owner: ActorId | None = None
    lifecycle: str | None = None
    provenance: list[KnowledgeEvidence] = Field(default_factory=list)
    external_refs: list[ExternalReference] = Field(default_factory=list)


class InterfaceType(StrEnum):
    REST = "rest"
    GRAPHQL = "graphql"
    GRPC = "grpc"
    MESSAGE_TOPIC = "message_topic"
    PYTHON_PUBLIC = "python_public"
    DATABASE_CONTRACT = "database_contract"
    CLI = "cli"


class Interface(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    component_id: uuid.UUID
    type: InterfaceType = InterfaceType.REST
    name: str
    schema_ref: str | None = None
    external_refs: list[ExternalReference] = Field(default_factory=list)


class ResourceType(StrEnum):
    POSTGRESQL = "postgresql"
    REDIS = "redis"
    KAFKA = "kafka"
    S3 = "s3"
    MINIO = "minio"
    KUBERNETES = "kubernetes"
    FILESYSTEM = "filesystem"
    MESSAGE_BROKER = "message_broker"
    EXTERNAL_SERVICE = "external_service"


class Resource(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: ProjectId
    name: str
    resource_type: ResourceType = ResourceType.EXTERNAL_SERVICE
    external_refs: list[ExternalReference] = Field(default_factory=list)
    provenance: list[KnowledgeEvidence] = Field(default_factory=list)
