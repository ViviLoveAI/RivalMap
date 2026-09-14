from rivalmap.contracts import (
    AgentEvent,
    AgentEventType,
    DegradationLevel,
    IntelligenceEvent,
    IntelligenceEventType,
    MarketBrief,
    OrchestratorDecision,
    ResearchEvent,
    ResearchEventType,
    ResearchSummary,
    RunStatus,
    VisualizationDelta,
)
from rivalmap.vertical_slice import BedrockVerticalSlice


class FakeFramer:
    def frame(self, product_idea, *, target_user, problem):
        return MarketBrief(
            product_idea=product_idea,
            target_user=target_user,
            problem=problem,
        )


class FakeProgressiveOrchestrator:
    def stream(self, brief):
        summary = ResearchSummary(
            candidates_found=1,
            passed=1,
            queries_completed=1,
            research_continuing=True,
        )
        yield AgentEvent(
            event=AgentEventType.RESEARCH_PROGRESS,
            run_status=RunStatus.RESEARCHING,
            message="Candidate found.",
            research_summary=summary,
            research_event=ResearchEvent(
                event=ResearchEventType.CANDIDATE_FOUND,
                summary=summary,
            ),
        )
        yield AgentEvent(
            event=AgentEventType.RESEARCH_PROGRESS,
            run_status=RunStatus.RESEARCHING,
            message="Candidate validated.",
            research_summary=summary,
            research_event=ResearchEvent(
                event=ResearchEventType.CANDIDATE_VALIDATED,
                summary=summary,
            ),
        )
        yield AgentEvent(
            event=AgentEventType.INTELLIGENCE_PROGRESS,
            run_status=RunStatus.ENRICHING,
            message="Profile ready.",
            intelligence_event=IntelligenceEvent(
                event=IntelligenceEventType.PRODUCT_PROFILE_READY,
                candidate_id="candidate-alpha",
            ),
        )
        yield AgentEvent(
            event=AgentEventType.PRESENTATION_UPDATE,
            run_status=RunStatus.INITIAL_READY,
            message="Initial map ready.",
            visualization_delta=VisualizationDelta(
                sequence=0,
                run_status=RunStatus.INITIAL_READY,
                degradation_level=DegradationLevel.D2,
            ),
        )
        yield AgentEvent(
            event=AgentEventType.COVERAGE_REVIEWED,
            run_status=RunStatus.COMPLETE,
            message="Research complete.",
            research_summary=summary.model_copy(update={"research_continuing": False}),
            orchestrator_decision=OrchestratorDecision(action="COMPLETE"),
        )


def test_vertical_slice_records_safe_milestones_and_streams_map_before_completion():
    events = list(
        BedrockVerticalSlice(FakeFramer(), FakeProgressiveOrchestrator()).stream(
            "AI interview coach",
            target_user="job seekers",
            problem="interview practice",
        )
    )
    event_types = [event.event for event in events]
    map_index = event_types.index(AgentEventType.PRESENTATION_UPDATE)
    completion_index = event_types.index(AgentEventType.COVERAGE_REVIEWED)
    metrics = events[-1].latency_metrics

    assert map_index < completion_index
    assert metrics.framing_ms is not None
    assert metrics.first_research_result_ms is not None
    assert metrics.first_validated_candidate_ms is not None
    assert metrics.first_analyzed_profile_ms is not None
    assert metrics.first_useful_map_ms is not None
    assert metrics.initial_ready_ms is not None
    assert metrics.research_completion_ms is not None
    assert "chain_of_thought" not in events[-1].model_dump_json()


class FailingFramer:
    def frame(self, product_idea, *, target_user, problem):
        _ = product_idea, target_user, problem
        raise RuntimeError("Bedrock unavailable")


def test_framing_model_failure_preserves_explicit_input_and_continues():
    events = list(
        BedrockVerticalSlice(FailingFramer(), FakeProgressiveOrchestrator()).stream(
            "AI interview coach",
            target_user="job seekers",
            problem="interview practice",
        )
    )

    degraded = next(event for event in events if event.event == AgentEventType.AGENT_DEGRADED)
    updated = next(
        event for event in events if event.event == AgentEventType.MARKET_BRIEF_UPDATED
    )
    assert degraded.error_code == "FRAMING_AGENT_FAILED"
    assert updated.market_brief.target_user == "job seekers"
    assert AgentEventType.PRESENTATION_UPDATE in [event.event for event in events]
