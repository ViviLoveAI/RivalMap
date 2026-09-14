"""FastAPI boundary for standalone RivalMap."""

from __future__ import annotations

import inspect
import json
import uuid
from collections.abc import Callable, Iterator
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .contracts import (
    AgentEvent,
    MarketBrief,
    RivalMapRequest,
    RivalMapState,
    RuntimeEvent,
    RuntimeEventType,
)
from .refinement import ActiveRunRegistry, MarketBriefRefinement
from .runtime import RivalMapRuntime, event_payload


class HealthResponse(BaseModel):
    ok: bool = True
    service: str = "rivalmap"


def _sse(event: RuntimeEvent) -> str:
    return (
        f"event: {event.event.value}\n"
        f"data: {json.dumps(event_payload(event), ensure_ascii=False)}\n\n"
    )


def _agent_sse(event: AgentEvent) -> str:
    return f"event: {event.event.value}\ndata: {event.model_dump_json()}\n\n"


class ProgressiveRunner(Protocol):
    def stream(
        self,
        product_idea: str,
        *,
        target_user: str | None,
        problem: str | None,
        exclusions: list[str] | None = None,
        brief_provider: Callable[[], MarketBrief] | None = None,
    ) -> Iterator[AgentEvent]: ...


def _build_progressive_runner() -> ProgressiveRunner:
    from .vertical_slice import build_bedrock_vertical_slice

    return build_bedrock_vertical_slice()


def create_router(
    runtime: RivalMapRuntime | None = None,
    *,
    progressive_factory: Callable[[], ProgressiveRunner] | None = None,
    active_run_registry: ActiveRunRegistry | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["RivalMap"])
    runtime = runtime or RivalMapRuntime()
    progressive_factory = progressive_factory or _build_progressive_runner
    active_runs = active_run_registry or ActiveRunRegistry()

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @router.post("/runs", response_model=RivalMapState)
    def run(request: RivalMapRequest) -> RivalMapState:
        try:
            return runtime.run(request)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/runs/stream")
    def stream(request: RivalMapRequest) -> StreamingResponse:
        def generate() -> Iterator[str]:
            try:
                yield from (_sse(event) for event in runtime.stream(request))
            except Exception as exc:  # noqa: BLE001 - typed event at HTTP boundary
                yield _sse(
                    RuntimeEvent(
                        event=RuntimeEventType.RUN_FAILED,
                        message=str(exc),
                        data={"error": type(exc).__name__},
                    )
                )

        return StreamingResponse(generate(), media_type="text/event-stream")

    @router.post("/v1/runs/stream")
    def progressive_stream(request: RivalMapRequest) -> StreamingResponse:
        run_id = uuid.uuid4().hex
        brief_state = active_runs.add(
            run_id,
            MarketBrief(
                product_idea=request.idea,
                target_user=request.target_user,
                problem=request.problem,
                exclusions=request.exclusions,
            ),
        )

        def generate() -> Iterator[str]:
            try:
                runner = progressive_factory()
                parameters = inspect.signature(runner.stream).parameters
                extra = (
                    {
                        "exclusions": request.exclusions,
                        "brief_provider": brief_state.get,
                    }
                    if "brief_provider" in parameters
                    else {}
                )
                for event in runner.stream(
                    request.idea,
                    target_user=request.target_user,
                    problem=request.problem,
                    **extra,
                ):
                    yield _agent_sse(event)
            except Exception:  # noqa: BLE001 - public stream remains sanitized
                payload: dict[str, Any] = {
                    "event": "run_failed",
                    "run_status": "FAILED",
                    "message": "RivalMap could not complete this run.",
                    "error_code": "PROGRESSIVE_RUN_FAILED",
                }
                yield f"event: run_failed\ndata: {json.dumps(payload)}\n\n"
            finally:
                active_runs.remove(run_id)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-RivalMap-Run-Id": run_id,
                "Access-Control-Expose-Headers": "X-RivalMap-Run-Id",
            },
        )

    @router.post("/v1/runs/{run_id}/refine", response_model=MarketBrief)
    def refine_run(run_id: str, refinement: MarketBriefRefinement) -> MarketBrief:
        brief_state = active_runs.get(run_id)
        if brief_state is None:
            raise HTTPException(status_code=404, detail="Active RivalMap run not found")
        return brief_state.refine(refinement)

    return router
