"""Provider routing interfaces for future bounded synthesis.

Copied/adapted from MarketCompass frozen baseline ca1356c. No concrete model
provider is introduced in this extraction slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class ModelProvider(Protocol):
    provider_name: str

    def generate(
        self,
        schema: type[ModelT],
        *,
        system: str,
        payload: dict,
    ) -> ModelT:
        """Generate one schema-validated object or raise a provider error."""


class ModelRouter(Protocol):
    def generate(
        self,
        schema: type[ModelT],
        *,
        system: str,
        payload: dict,
        task: str,
    ) -> ModelT:
        """Return a usable structured result for a bounded task."""


@dataclass(frozen=True)
class SingleProviderModelRouter:
    primary: ModelProvider

    def generate(
        self,
        schema: type[ModelT],
        *,
        system: str,
        payload: dict,
        task: str,
    ) -> ModelT:
        _ = task
        return self.primary.generate(schema, system=system, payload=payload)
