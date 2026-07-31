from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from agent_core.agent_platform.config.models import (
    AgentPlatformConfig,
    DEFAULT_AGENT_PLATFORM_CONFIG,
)


def load_agent_platform_config(path: str | Path | None = None) -> AgentPlatformConfig:
    configured_path = path or os.getenv("AGENT_PLATFORM_CONFIG_FILE")
    if configured_path is None:
        return DEFAULT_AGENT_PLATFORM_CONFIG.model_copy(deep=True)
    config_path = Path(configured_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return load_agent_platform_config_from_mapping(payload)


def load_agent_platform_config_from_mapping(payload: Mapping[str, Any]) -> AgentPlatformConfig:
    return AgentPlatformConfig.model_validate(payload)
