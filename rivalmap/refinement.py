"""Short-lived, thread-safe MarketBrief refinement state for active runs."""

from __future__ import annotations

from threading import Lock

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import MarketBrief


class MarketBriefRefinement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exclusions: list[str] | None = None
    competitive_scope: str | None = Field(default=None, min_length=1)
    priority_dimension: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def has_update(self) -> MarketBriefRefinement:
        if all(
            value is None
            for value in (
                self.exclusions,
                self.competitive_scope,
                self.priority_dimension,
            )
        ):
            raise ValueError("at least one refinement field is required")
        return self


class ActiveRunBrief:
    def __init__(self, brief: MarketBrief) -> None:
        self._brief = brief
        self._lock = Lock()

    def get(self) -> MarketBrief:
        with self._lock:
            return self._brief.model_copy(deep=True)

    def refine(self, refinement: MarketBriefRefinement) -> MarketBrief:
        updates = {
            name: value
            for name, value in refinement.model_dump(exclude_none=True).items()
        }
        with self._lock:
            self._brief = self._brief.model_copy(update=updates)
            return self._brief.model_copy(deep=True)


class ActiveRunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, ActiveRunBrief] = {}
        self._lock = Lock()

    def add(self, run_id: str, brief: MarketBrief) -> ActiveRunBrief:
        state = ActiveRunBrief(brief)
        with self._lock:
            self._runs[run_id] = state
        return state

    def get(self, run_id: str) -> ActiveRunBrief | None:
        with self._lock:
            return self._runs.get(run_id)

    def remove(self, run_id: str) -> None:
        with self._lock:
            self._runs.pop(run_id, None)
