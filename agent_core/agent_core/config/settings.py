from __future__ import annotations

from socket import gethostname

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    app_env: str = "development"
    app_log_level: str = "INFO"
    app_host: str = "0.0.0.0"
    app_port: int = 8090

    database_url: str = Field(
        validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_DSN"),
    )
    checkpoint_database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CHECKPOINT_DATABASE_URL", "LANGGRAPH_POSTGRES_DSN"),
    )
    redis_url: str = "redis://localhost:6379/0"

    llm_base_url: str
    llm_model: str
    llm_api_key: str = "local-not-secret"
    llm_request_timeout_seconds: int = 180
    llm_max_retries: int = 2
    llm_context_window: int = 29696
    llm_max_output_tokens: int = 4096
    llm_temperature: float = 0.1

    openproject_base_url: str
    openproject_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENPROJECT_API_KEY", "OPENPROJECT_API_TOKEN"),
    )
    openproject_api_token_file: str | None = None
    openproject_webhook_secret: str = ""
    openproject_agent_user_id: str | None = None
    openproject_request_timeout_seconds: int = 30

    neo4j_uri: str
    neo4j_username: str = Field(
        validation_alias=AliasChoices("NEO4J_USERNAME", "NEO4J_USER"),
    )
    neo4j_password: str
    neo4j_database: str = "neo4j"

    weaviate_http_host: str = "localhost"
    weaviate_http_port: int = 8080
    weaviate_grpc_host: str = "localhost"
    weaviate_grpc_port: int = 50051
    weaviate_secure: bool = False

    repository_mount_root: str = "/workspace/repositories"
    default_repository_access_mode: str = "READ_ONLY"
    command_output_limit_bytes: int = 1_048_576
    default_command_timeout_seconds: int = 600

    approval_plan_required: bool = True
    approval_repository_write_required: bool = False
    approval_task_completion_required: bool = True

    worker_concurrency: int = 2
    worker_lease_seconds: int = 300
    worker_max_event_attempts: int = 5
    flow_worker_id: str = Field(default_factory=gethostname)

    @property
    def neo4j_user(self) -> str:
        return self.neo4j_username


settings = Settings()
