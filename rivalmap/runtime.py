"""Standalone RivalMap runtime."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from .adapters.exa import ExaDiscoveryService
from .contracts import (
    AnalysisService,
    DiscoveryService,
    RivalMapRequest,
    RivalMapState,
    RuntimeEvent,
    RuntimeEventType,
    SessionContext,
    WorkingState,
)
from .evidence import compact_evidence_view
from .rival_map import merge_rival_map_state
from .services import DeterministicAnalysisService
from .structure import build_market_structure, product_map_from_structure


@dataclass
class RivalMapRuntime:
    discovery: DiscoveryService | None = None
    analysis: AnalysisService | None = None

    def __post_init__(self) -> None:
        if self.discovery is None:
            self.discovery = ExaDiscoveryService()
        if self.analysis is None:
            self.analysis = DeterministicAnalysisService()

    def run(self, request: RivalMapRequest) -> RivalMapState:
        state = self._run_working_state(request)
        assert state.rival_map_state is not None
        return state.rival_map_state

    def stream(self, request: RivalMapRequest) -> Iterator[RuntimeEvent]:
        session = SessionContext(
            product_idea=request.idea,
            target_user=request.target_user,
            problem=request.problem,
            exclusions=request.exclusions,
        )
        yield RuntimeEvent(
            event=RuntimeEventType.RUN_STARTED,
            message="RivalMap run started.",
            data={"idea": request.idea},
        )
        yield RuntimeEvent(
            event=RuntimeEventType.DISCOVERY_STARTED,
            message=f"正在搜索：{request.query_text}",
            data={"query": request.query_text},
        )
        evidence = self.discovery.discover(request) if self.discovery else []
        yield RuntimeEvent(
            event=RuntimeEventType.EVIDENCE_READY,
            message=f"找到 {len(evidence)} 条候选证据。",
            data={
                "count": len(evidence),
                "items": [item.model_dump(mode="json") for item in compact_evidence_view(evidence)],
            },
        )
        structure = build_market_structure(evidence)
        yield RuntimeEvent(
            event=RuntimeEventType.STRUCTURE_READY,
            message=structure.summary,
            data={"structure": structure.model_dump(mode="json")},
        )
        base_map = product_map_from_structure(structure)
        yield RuntimeEvent(
            event=RuntimeEventType.BASE_MAP_READY,
            message="Base map ready." if base_map else "Base map not available yet.",
            data={"base_map": base_map.model_dump(mode="json") if base_map else None},
        )
        analysis = self.analysis.analyze(request, evidence, structure) if self.analysis else None
        yield RuntimeEvent(
            event=RuntimeEventType.ANALYSIS_READY,
            message=analysis.summary if analysis else "Analysis unavailable.",
            data={"analysis": analysis.model_dump(mode="json") if analysis else None},
        )
        rival_map_state = merge_rival_map_state(
            session=session,
            evidence=evidence,
            market_structure=structure,
            base_map=base_map,
            analysis=analysis,
        )
        yield RuntimeEvent(
            event=RuntimeEventType.RIVAL_MAP_READY,
            message=rival_map_state.summary,
            data={"rival_map_state": rival_map_state.model_dump(mode="json")},
        )

    def _run_working_state(self, request: RivalMapRequest) -> WorkingState:
        session = SessionContext(
            product_idea=request.idea,
            target_user=request.target_user,
            problem=request.problem,
            exclusions=request.exclusions,
        )
        evidence = self.discovery.discover(request) if self.discovery else []
        structure = build_market_structure(evidence)
        base_map = product_map_from_structure(structure)
        analysis = self.analysis.analyze(request, evidence, structure) if self.analysis else None
        rival_map_state = merge_rival_map_state(
            session=session,
            evidence=evidence,
            market_structure=structure,
            base_map=base_map,
            analysis=analysis,
        )
        return WorkingState(
            request=request,
            session=session,
            evidence=evidence,
            market_structure=structure,
            base_map=base_map,
            analysis=analysis,
            rival_map_state=rival_map_state,
        )


def event_payload(event: RuntimeEvent) -> dict[str, Any]:
    return {"event": event.event.value, "message": event.message, "data": event.data}
