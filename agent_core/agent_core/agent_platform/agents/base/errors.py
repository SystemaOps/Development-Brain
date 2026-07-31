from __future__ import annotations

from agent_core.agent_platform.agents.base.contracts import AgentErrorCategory


class AgentPlatformError(Exception):
    category = AgentErrorCategory.NON_RETRYABLE_ERROR


class AgentValidationError(AgentPlatformError, ValueError):
    category = AgentErrorCategory.VALIDATION_ERROR


class AgentConfigurationError(AgentPlatformError, ValueError):
    category = AgentErrorCategory.CONFIGURATION_ERROR


class AgentDependencyError(AgentPlatformError, RuntimeError):
    category = AgentErrorCategory.DEPENDENCY_ERROR


class AgentCheckpointError(AgentPlatformError, RuntimeError):
    category = AgentErrorCategory.CHECKPOINT_ERROR


class AgentBlockedError(AgentPlatformError, RuntimeError):
    category = AgentErrorCategory.BLOCKED_ERROR
