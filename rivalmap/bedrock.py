"""Explicit, injectable Amazon Bedrock configuration for RivalMap agents."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


class BedrockConfigurationError(ValueError):
    """Raised before startup when required Bedrock settings are invalid."""


class BedrockProviderError(RuntimeError):
    """Provider failure safe to translate into a degraded RivalMap event."""


_ROLES = ("framing", "orchestrator", "research", "intelligence", "presentation")
_DEFAULT_MAX_TOKENS = {
    "framing": 512,
    "orchestrator": 768,
    "research": 768,
    "intelligence": 1536,
    "presentation": 768,
}
_DEFAULT_TEMPERATURE = {
    "framing": 0.0,
    "orchestrator": 0.0,
    "research": 0.1,
    "intelligence": 0.1,
    "presentation": 0.2,
}


@dataclass(frozen=True)
class AgentBedrockConfig:
    model_id: str
    temperature: float
    max_tokens: int


@dataclass(frozen=True)
class BedrockSettings:
    region: str
    agents: dict[str, AgentBedrockConfig]
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 60.0
    max_attempts: int = 3

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> BedrockSettings:
        values = os.environ if environ is None else environ
        region = values.get("RIVALMAP_AWS_REGION", "").strip()
        base_model = values.get("RIVALMAP_BEDROCK_MODEL_ID", "").strip()
        if not region:
            raise BedrockConfigurationError("RIVALMAP_AWS_REGION is required")
        if not re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z]+-\d", region):
            raise BedrockConfigurationError("RIVALMAP_AWS_REGION is not a valid AWS region")
        if not base_model:
            raise BedrockConfigurationError("RIVALMAP_BEDROCK_MODEL_ID is required")

        agents = {}
        for role in _ROLES:
            prefix = f"RIVALMAP_BEDROCK_{role.upper()}"
            model_id = (values.get(f"{prefix}_MODEL_ID") or base_model).strip()
            if not model_id:
                raise BedrockConfigurationError(f"{prefix}_MODEL_ID cannot be empty")
            temperature = _float_setting(
                values,
                f"{prefix}_TEMPERATURE",
                _DEFAULT_TEMPERATURE[role],
                minimum=0,
                maximum=1,
            )
            max_tokens = _int_setting(
                values,
                f"{prefix}_MAX_TOKENS",
                _DEFAULT_MAX_TOKENS[role],
                minimum=64,
                maximum=8192,
            )
            agents[role] = AgentBedrockConfig(model_id, temperature, max_tokens)
        return cls(
            region=region,
            agents=agents,
            connect_timeout_seconds=_float_setting(
                values,
                "RIVALMAP_BEDROCK_CONNECT_TIMEOUT_SECONDS",
                5.0,
                minimum=0.1,
                maximum=60,
            ),
            read_timeout_seconds=_float_setting(
                values,
                "RIVALMAP_BEDROCK_READ_TIMEOUT_SECONDS",
                60.0,
                minimum=1,
                maximum=300,
            ),
            max_attempts=_int_setting(
                values,
                "RIVALMAP_BEDROCK_MAX_ATTEMPTS",
                3,
                minimum=1,
                maximum=10,
            ),
        )


@dataclass(frozen=True)
class BedrockAgentModels:
    framing: Any
    orchestrator: Any
    research: Any
    intelligence: Any
    presentation: Any

    def as_mapping(self) -> dict[str, Any]:
        return {role: getattr(self, role) for role in _ROLES}


def create_bedrock_models(
    settings: BedrockSettings,
    *,
    model_factory: Callable[..., Any] | None = None,
    client_config_factory: Callable[..., Any] | None = None,
) -> BedrockAgentModels:
    """Create role-specific Strands models without resolving credentials in RivalMap."""

    try:
        if model_factory is None:
            from strands.models import BedrockModel

            model_factory = BedrockModel
        if client_config_factory is None:
            from botocore.config import Config

            client_config_factory = Config
        client_config = client_config_factory(
            retries={"max_attempts": settings.max_attempts, "mode": "standard"},
            connect_timeout=settings.connect_timeout_seconds,
            read_timeout=settings.read_timeout_seconds,
        )
        models = {
            role: model_factory(
                model_id=config.model_id,
                region_name=settings.region,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                boto_client_config=client_config,
            )
            for role, config in settings.agents.items()
        }
    except Exception as exc:
        raise BedrockProviderError("Unable to initialize the Bedrock model provider") from exc
    return BedrockAgentModels(**models)


def _float_setting(
    values: Mapping[str, str],
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(values.get(key, str(default)))
    except ValueError as exc:
        raise BedrockConfigurationError(f"{key} must be numeric") from exc
    if not minimum <= value <= maximum:
        raise BedrockConfigurationError(f"{key} must be between {minimum} and {maximum}")
    return value


def _int_setting(
    values: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(values.get(key, str(default)))
    except ValueError as exc:
        raise BedrockConfigurationError(f"{key} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise BedrockConfigurationError(f"{key} must be between {minimum} and {maximum}")
    return value
