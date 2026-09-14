"""Standalone real-provider RivalMap V1 vertical slice."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass

from dotenv import load_dotenv

from .adapters.exa import ExaDiscoveryService
from .agents import (
    MarketIntelligenceAgent,
    PresentationAgent,
    ProgressiveOrchestratorAgent,
    ResearchAgent,
    build_strands_agent_set,
)
from .bedrock import (
    BedrockConfigurationError,
    BedrockProviderError,
    BedrockSettings,
    create_bedrock_models,
)
from .contracts import (
    AgentEvent,
    AgentEventType,
    IntelligenceEventType,
    LatencyMetrics,
    MarketBrief,
    ResearchEventType,
    RunStatus,
)
from .market_intelligence import MarketIntelligenceService
from .research import ParallelResearchService
from .strands_execution import (
    StrandsMarketBriefFramer,
    StrandsPresentationAgent,
    StrandsResearchPlanner,
    StrandsSemanticAnalyzer,
    StrandsStructuredAnalyzer,
)


@dataclass
class _LatencyRecorder:
    started: float
    metrics: LatencyMetrics

    @classmethod
    def start(cls) -> _LatencyRecorder:
        return cls(time.monotonic(), LatencyMetrics())

    def mark(self, field: str) -> None:
        if getattr(self.metrics, field) is None:
            setattr(self.metrics, field, round((time.monotonic() - self.started) * 1000, 3))


class BedrockVerticalSlice:
    def __init__(self, framer: StrandsMarketBriefFramer, orchestrator: ProgressiveOrchestratorAgent):
        self.framer = framer
        self.orchestrator = orchestrator

    def stream(
        self,
        product_idea: str,
        *,
        target_user: str | None,
        problem: str | None,
    ) -> Iterator[AgentEvent]:
        latency = _LatencyRecorder.start()
        input_brief = MarketBrief(
            product_idea=product_idea,
            target_user=target_user,
            problem=problem,
        )
        yield AgentEvent(
            event=AgentEventType.FRAMING_STARTED,
            run_status=RunStatus.FRAMING,
            message="Bedrock market framing started.",
            market_brief=input_brief,
            latency_metrics=latency.metrics.model_copy(deep=True),
        )
        try:
            brief = self.framer.frame(
                product_idea,
                target_user=target_user,
                problem=problem,
            )
        except Exception:  # noqa: BLE001 - preserve explicit user framing
            brief = input_brief
            latency.mark("framing_ms")
            yield AgentEvent(
                event=AgentEventType.AGENT_DEGRADED,
                run_status=RunStatus.FRAMING,
                message="Market framing model failed; explicit user fields were preserved.",
                market_brief=brief,
                latency_metrics=latency.metrics.model_copy(deep=True),
                error_code="FRAMING_AGENT_FAILED",
            )
        else:
            latency.mark("framing_ms")
        yield AgentEvent(
            event=AgentEventType.MARKET_BRIEF_UPDATED,
            run_status=(
                RunStatus.RESEARCHING
                if brief.problem and brief.target_user
                else RunStatus.FRAMING
            ),
            message="Typed MarketBrief ready.",
            market_brief=brief,
            latency_metrics=latency.metrics.model_copy(deep=True),
        )

        for event in self.orchestrator.stream(brief):
            if event.research_event is not None:
                if event.research_event.event in {
                    ResearchEventType.CANDIDATE_FOUND,
                    ResearchEventType.RESEARCH_BATCH_UPDATED,
                }:
                    latency.mark("first_research_result_ms")
                if event.research_event.event == ResearchEventType.CANDIDATE_VALIDATED:
                    latency.mark("first_validated_candidate_ms")
            if (
                event.intelligence_event is not None
                and event.intelligence_event.event
                == IntelligenceEventType.PRODUCT_PROFILE_READY
            ):
                latency.mark("first_analyzed_profile_ms")
            if event.visualization_delta is not None:
                if any(
                    node.node_type == "PRODUCT"
                    for node in event.visualization_delta.upsert_nodes
                ):
                    latency.mark("first_renderable_map_ms")
                if event.visualization_delta.run_status == RunStatus.INITIAL_READY:
                    latency.mark("first_useful_map_ms")
            if (
                event.event == AgentEventType.COVERAGE_REVIEWED
                and event.orchestrator_decision is not None
                and event.orchestrator_decision.action == "COMPLETE"
                and event.research_summary is not None
                and event.research_summary.queries_completed
                + event.research_summary.queries_failed
                > 0
            ):
                latency.mark("research_completion_ms")
            yield event.model_copy(
                update={"latency_metrics": latency.metrics.model_copy(deep=True)}
            )


def build_bedrock_vertical_slice(
    settings: BedrockSettings | None = None,
) -> BedrockVerticalSlice:
    settings = settings or BedrockSettings.from_env()
    models = create_bedrock_models(settings)
    research = ResearchAgent(ParallelResearchService(ExaDiscoveryService()))
    intelligence = MarketIntelligenceAgent(MarketIntelligenceService())
    presentation = PresentationAgent()
    agents = build_strands_agent_set(
        model=models.as_mapping(),
        research=research,
        intelligence=intelligence,
        presentation=presentation,
    )
    research.planner = StrandsResearchPlanner(agents.research)
    intelligence.service = MarketIntelligenceService(
        StrandsStructuredAnalyzer(agents.market_intelligence),
        StrandsSemanticAnalyzer(agents.market_intelligence),
    )
    model_presentation = StrandsPresentationAgent(agents.presentation)
    orchestrator = ProgressiveOrchestratorAgent(
        research,
        intelligence,
        model_presentation,
        decision_maker=agents.decision_maker,
    )
    return BedrockVerticalSlice(
        StrandsMarketBriefFramer(agents.market_framing),
        orchestrator,
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the RivalMap Bedrock vertical slice")
    parser.add_argument("idea")
    parser.add_argument("--target-user", required=True)
    parser.add_argument("--problem", required=True)
    args = parser.parse_args(argv)
    try:
        runner = build_bedrock_vertical_slice()
        for event in runner.stream(
            args.idea,
            target_user=args.target_user,
            problem=args.problem,
        ):
            print(event.model_dump_json())
    except (BedrockConfigurationError, BedrockProviderError) as exc:
        print(f"RivalMap Bedrock startup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
