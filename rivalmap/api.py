"""FastAPI boundary for standalone RivalMap."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .contracts import RivalMapRequest, RivalMapState, RuntimeEvent, RuntimeEventType
from .runtime import RivalMapRuntime, event_payload


class HealthResponse(BaseModel):
    ok: bool = True
    service: str = "rivalmap"


def _sse(event: RuntimeEvent) -> str:
    return (
        f"event: {event.event.value}\n"
        f"data: {json.dumps(event_payload(event), ensure_ascii=False)}\n\n"
    )

def create_router(runtime: RivalMapRuntime | None = None) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["RivalMap"])
    runtime = runtime or RivalMapRuntime()

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

    return router
