"""Typed runtime settings (Phase 21).

One ``BrainSettings`` hierarchy drives every runtime process (API, worker,
scheduler, CLI).  Settings support environment variables, ``.env`` files, and
explicit construction in tests.  Adapters receive resolved settings; they never
read environment variables deep inside their implementation.

Every integration capability carries ``enabled`` / ``provider`` / ``required``
so optional providers can be switched off or reported unavailable without
breaking the Brain (Tasks 21.2, 21.3).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BrainRuntimeSettings(BaseSettings):
    """Process-level runtime settings."""

    model_config = SettingsConfigDict(
        env_prefix="BRAIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"


class PostgresSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRAIN_DATABASE_", env_file=".env", extra="ignore")

    url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10
    pool_pre_ping: bool = True


class Neo4jSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRAIN_NEO4J_", env_file=".env", extra="ignore")

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "password"
    database: str = "neo4j"


class WeaviateSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRAIN_WEAVIATE_", env_file=".env", extra="ignore")

    host: str = "localhost"
    port: int = 8080
    grpc_port: int = 50051
    scheme: str = "http"
    class_name: str = "SemanticRecord"


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRAIN_REDIS_", env_file=".env", extra="ignore")

    url: str = "redis://localhost:6379/0"
    queue_name: str = "brain:commands"
    provider: str = "inmemory"


class ArtifactStoreSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BRAIN_ARTIFACTS_", env_file=".env", extra="ignore"
    )

    provider: str = "local"
    base_dir: str = ".brain/artifacts"


class ProviderCapabilitySettings(BaseSettings):
    """Common enabled/provider/required triple (Task 21.3)."""

    model_config = SettingsConfigDict(extra="ignore")

    enabled: bool = True
    provider: str = ""
    required: bool = False


class WorkManagementSettings(ProviderCapabilitySettings):
    provider: str = "internal"
    base_url: str = ""
    api_key: str = ""
    project_id: str = ""
    brain_actor_id: str = ""


class DocumentationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BRAIN_DOCUMENTATION_", env_file=".env", extra="ignore"
    )

    git_enabled: bool = True
    git_root: str = "."
    xwiki_enabled: bool = False
    xwiki_url: str = ""
    xwiki_required: bool = False


class DocumentConversionSettings(ProviderCapabilitySettings):
    provider: str = "native"
    base_url: str = ""


class SoftwareCatalogSettings(ProviderCapabilitySettings):
    provider: str = "derived"
    external_type: str = "backstage"
    external_enabled: bool = False
    external_url: str = ""


class SourceControlSettings(ProviderCapabilitySettings):
    provider: str = "local"


class ExecutorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRAIN_EXECUTOR_", env_file=".env", extra="ignore")

    coding_provider: str = "fake"
    pi_url: str = ""
    pi_api_key: str = ""


class VerificationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BRAIN_VERIFICATION_", env_file=".env", extra="ignore"
    )

    require_pass_before_pr: bool = True
    timeout_seconds: int = 300


class AutomationPolicySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BRAIN_AUTOMATION_", env_file=".env", extra="ignore"
    )

    run_on_assignment: bool = True
    auto_retry_verification_failure: bool = True
    auto_create_pr: bool = False


class PullRequestSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BRAIN_PULL_REQUEST_", env_file=".env", extra="ignore"
    )

    provider: str = "fake"
    gitlab_url: str = ""
    gitlab_api_key: str = ""
    gitlab_project: str = ""


class HumanApprovalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRAIN_APPROVAL_", env_file=".env", extra="ignore")

    architecture_changes: bool = True
    database_migrations: bool = True
    security_sensitive_changes: bool = True
    normal_code_changes: bool = False


class BrainSettings(BaseSettings):
    """Complete runtime configuration for the Brain platform.

    Nested models read their own ``BRAIN_*`` environment prefixes; explicit
    construction in tests passes fully resolved sub-settings.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    runtime: BrainRuntimeSettings = Field(default_factory=BrainRuntimeSettings)
    storage_state: PostgresSettings = Field(default_factory=PostgresSettings)
    storage_graph: Neo4jSettings = Field(default_factory=Neo4jSettings)
    storage_semantic: WeaviateSettings = Field(default_factory=WeaviateSettings)
    storage_queue: RedisSettings = Field(default_factory=RedisSettings)
    storage_artifacts: ArtifactStoreSettings = Field(default_factory=ArtifactStoreSettings)
    work_management: WorkManagementSettings = Field(default_factory=WorkManagementSettings)
    documentation: DocumentationSettings = Field(default_factory=DocumentationSettings)
    document_conversion: DocumentConversionSettings = Field(
        default_factory=DocumentConversionSettings
    )
    software_catalog: SoftwareCatalogSettings = Field(default_factory=SoftwareCatalogSettings)
    source_control: SourceControlSettings = Field(default_factory=SourceControlSettings)
    executors: ExecutorSettings = Field(default_factory=ExecutorSettings)
    verification: VerificationSettings = Field(default_factory=VerificationSettings)
    automation: AutomationPolicySettings = Field(default_factory=AutomationPolicySettings)
    pull_requests: PullRequestSettings = Field(default_factory=PullRequestSettings)
    human_approval: HumanApprovalSettings = Field(default_factory=HumanApprovalSettings)


__all__ = [
    "ArtifactStoreSettings",
    "AutomationPolicySettings",
    "BrainRuntimeSettings",
    "BrainSettings",
    "DocumentConversionSettings",
    "DocumentationSettings",
    "ExecutorSettings",
    "HumanApprovalSettings",
    "Neo4jSettings",
    "PostgresSettings",
    "ProviderCapabilitySettings",
    "RedisSettings",
    "SoftwareCatalogSettings",
    "SourceControlSettings",
    "VerificationSettings",
    "WeaviateSettings",
    "WorkManagementSettings",
]
