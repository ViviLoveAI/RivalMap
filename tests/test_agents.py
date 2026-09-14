import json
import time

from rivalmap.agents import (
    INTELLIGENCE_DEFINITION,
    MARKET_FRAMING_DEFINITION,
    ORCHESTRATOR_DEFINITION,
    PRESENTATION_DEFINITION,
    RESEARCH_DEFINITION,
    MarketFramingAgent,
    MarketIntelligenceAgent,
    PresentationAgent,
    ProgressiveOrchestratorAgent,
    ResearchAgent,
    build_strands_agent_set,
)
from rivalmap.contracts import (
    AgentEventType,
    CandidateRecord,
    CandidateValidation,
    EvidenceItem,
    EvidenceRelation,
    MarketBrief,
    OrchestrationBudget,
    OrchestratorDecision,
    ResearchBatch,
    ResearchBranch,
    ResearchEvent,
    ResearchEventType,
    ResearchSummary,
    RunStatus,
    SearchSeed,
    Source,
    SourceQuality,
)
from rivalmap.market_intelligence import MarketIntelligenceService


def _brief() -> MarketBrief:
    return MarketBrief(
        product_idea="AI interview coaching platform",
        target_user="job seekers",
        problem="practice interviews and receive feedback",
    )


def _batch(name: str, branch: ResearchBranch = ResearchBranch.DIRECT) -> ResearchBatch:
    evidence_id = f"ev-{name}"
    candidate_id = f"candidate-{name}"
    evidence = EvidenceItem(
        evidence_id=evidence_id,
        topic=name,
        claim=f"{name} is an interview coaching product.",
        source=Source(
            url=f"https://{name}.example",
            title=name,
            quality=SourceQuality.PRIMARY,
        ),
        evidence_text=f"{name} provides interview practice and feedback.",
        relation=EvidenceRelation.SUPPORTS,
        confidence=0.9,
    )
    seed = SearchSeed(seed_id=f"seed-{name}", query=f"query {name}", branch=branch)
    return ResearchBatch(
        batch_id=f"batch-{name}",
        seed=seed,
        seeds=[seed],
        evidence=[evidence],
        candidates=[
            CandidateRecord(
                candidate_id=candidate_id,
                name=name,
                description=evidence.claim,
                source_evidence_ids=[evidence_id],
                canonical_url=evidence.source.url,
                domain=f"{name}.example",
            )
        ],
        validations=[
            CandidateValidation(
                candidate_id=candidate_id,
                status="PASS",
                reason="Evidence-backed candidate.",
                source_evidence_ids=[evidence_id],
                is_product_or_company=True,
                relevance_score=0.9,
                identity_confidence=0.9,
                source_quality=SourceQuality.PRIMARY,
                evidence_coverage=1,
            )
        ],
    )


class FakeResearchAgent:
    def __init__(self, waves, *, pause_after_batch=0.0, fail=False):
        self.waves = waves
        self.pause_after_batch = pause_after_batch
        self.fail = fail
        self.calls = []

    def stream(self, brief, *, branches=None, wave=1):
        self.calls.append((brief, branches, wave))
        if self.fail:
            raise RuntimeError("research agent failed")
        batch, summary = self.waves[min(wave - 1, len(self.waves) - 1)]
        yield ResearchEvent(
            event=ResearchEventType.RESEARCH_BATCH_UPDATED,
            branch=batch.seed.branch,
            batch=batch,
            summary=summary.model_copy(update={"research_continuing": True}),
        )
        if self.pause_after_batch:
            time.sleep(self.pause_after_batch)
        yield ResearchEvent(
            event=ResearchEventType.RESEARCH_WAVE_COMPLETE,
            batch=batch,
            summary=summary.model_copy(update={"research_continuing": False}),
        )


class FakeDecisionMaker:
    def __init__(self, actions, *, delays=None):
        self.actions = list(actions)
        self.delays = list(delays or [])
        self.calls = []

    def decide(self, metrics):
        self.calls.append(metrics)
        call_index = len(self.calls) - 1
        if call_index < len(self.delays):
            time.sleep(self.delays[call_index])
        if not self.actions:
            raise AssertionError("unexpected orchestration decision request")
        return self.actions.pop(0)


class SlowPresentationAgent:
    def __init__(self, delay):
        self.delay = delay
        self.delegate = PresentationAgent()

    def prepare(self, market_model, nodes_by_product, delta):
        time.sleep(self.delay)
        return self.delegate.prepare(market_model, nodes_by_product, delta)


def _summary(*, passed, branches):
    return ResearchSummary(
        candidates_found=passed,
        passed=passed,
        queries_completed=len(branches),
        search_branches_covered=branches,
        research_continuing=False,
    )


def _broad():
    return OrchestratorDecision(
        action="CONTINUE_BROAD",
        target_branches=list(ResearchBranch),
    )


def _complete():
    return OrchestratorDecision(action="COMPLETE")


def _orchestrator(
    research,
    *,
    decisions=None,
    decision_maker=None,
    intelligence=None,
    budget=None,
    presentation=None,
):
    intelligence = intelligence or MarketIntelligenceAgent(MarketIntelligenceService())
    decision_maker = decision_maker or FakeDecisionMaker(decisions or [_broad(), _complete()])
    orchestrator = ProgressiveOrchestratorAgent(
        research,
        intelligence,
        presentation,
        decision_maker=decision_maker,
        budget=budget,
    )
    orchestrator.test_decision_maker = decision_maker
    return orchestrator


def test_market_framing_asks_one_progressive_question_at_a_time():
    framing = MarketFramingAgent()

    started = framing.start("AI interview coach")
    problem_update = framing.answer("Practice realistic interviews")
    customer_update = framing.answer("Job seekers")

    assert [event.event for event in started] == [
        AgentEventType.FRAMING_STARTED,
        AgentEventType.FRAMING_QUESTION,
    ]
    assert started[-1].question_field == "problem"
    assert problem_update[-1].question_field == "target_user"
    assert customer_update[0].run_status == RunStatus.RESEARCHING
    assert customer_update[-1].question_field == "exclusions"
    assert framing.research_ready

    refinement = framing.answer("generic recruiting suites")
    assert refinement[0].market_brief.problem == "Practice realistic interviews"
    assert refinement[0].market_brief.target_user == "Job seekers"
    assert refinement[0].market_brief.exclusions == ["generic recruiting suites"]
    assert framing.research_ready


def test_research_can_begin_before_optional_framing_question_is_answered():
    framing = MarketFramingAgent()
    events = framing.start(
        "AI interview coach",
        problem="Practice realistic interviews",
        target_user="Job seekers",
    )

    assert framing.research_ready
    assert events[-1].event == AgentEventType.FRAMING_QUESTION
    assert events[-1].question_field == "exclusions"
    assert events[-1].run_status == RunStatus.RESEARCHING


def test_orchestrator_invokes_research_agent_and_stops_on_sufficient_coverage():
    research = FakeResearchAgent(
        [(_batch("alpha"), _summary(passed=3, branches=list(ResearchBranch)[:3]))]
    )
    budget = OrchestrationBudget(
        minimum_passed_candidates=3,
        minimum_branches_covered=3,
    )

    orchestrator = _orchestrator(research, budget=budget)
    events = list(orchestrator.stream(_brief()))

    assert len(research.calls) == 1
    assert len(orchestrator.test_decision_maker.calls) == 2
    final_metrics = orchestrator.test_decision_maker.calls[-1]
    assert final_metrics.research_summary.passed == 3
    assert final_metrics.framing_sufficient
    assert final_metrics.remaining_research_waves == 2
    assert final_metrics.target_passed_candidates == 3
    assert final_metrics.target_branches_covered == 3
    reviews = [event for event in events if event.event == AgentEventType.COVERAGE_REVIEWED]
    assert reviews[-1].orchestrator_decision.action == "COMPLETE"
    assert events[-1].event == AgentEventType.ORCHESTRATION_COMPLETE


def test_orchestrator_requests_targeted_enrichment_for_missing_coverage():
    research = FakeResearchAgent(
        [
            (_batch("alpha"), _summary(passed=1, branches=[ResearchBranch.DIRECT])),
            (
                _batch("beta", ResearchBranch.ADJACENT),
                _summary(passed=2, branches=list(ResearchBranch)),
            ),
        ]
    )
    budget = OrchestrationBudget(
        minimum_passed_candidates=3,
        minimum_branches_covered=3,
    )

    decisions = [
        _broad(),
        OrchestratorDecision(
            action="FILL_GAP",
            target_branches=[ResearchBranch.ADJACENT, ResearchBranch.CATEGORY],
        ),
        _complete(),
    ]
    events = list(
        _orchestrator(research, decisions=decisions, budget=budget).stream(_brief())
    )

    enrichment = next(
        event for event in events if event.event == AgentEventType.ENRICHMENT_REQUESTED
    )
    assert enrichment.orchestrator_decision.action == "FILL_GAP"
    assert ResearchBranch.ADJACENT in enrichment.orchestrator_decision.target_branches
    assert len(research.calls) == 2


def test_next_orchestrator_decision_and_wave_read_latest_market_brief():
    current = {"brief": _brief()}

    class RefiningResearchAgent(FakeResearchAgent):
        def stream(self, brief, *, branches=None, wave=1):
            yield from super().stream(brief, branches=branches, wave=wave)
            if wave == 1:
                current["brief"] = current["brief"].model_copy(
                    update={
                        "exclusions": ["recruiting suites"],
                        "competitive_scope": "consumer coaching",
                        "priority_dimension": "feedback quality",
                    }
                )

    research = RefiningResearchAgent(
        [
            (_batch("alpha"), _summary(passed=1, branches=[ResearchBranch.DIRECT])),
            (_batch("beta"), _summary(passed=2, branches=list(ResearchBranch))),
        ]
    )
    decisions = [
        _broad(),
        OrchestratorDecision(
            action="FILL_GAP",
            target_branches=[ResearchBranch.ADJACENT],
        ),
        _complete(),
    ]
    orchestrator = _orchestrator(research, decisions=decisions)

    list(orchestrator.stream(_brief(), brief_provider=lambda: current["brief"]))

    reviewed = orchestrator.test_decision_maker.calls[1].market_brief
    assert reviewed.exclusions == ["recruiting suites"]
    assert reviewed.competitive_scope == "consumer coaching"
    assert reviewed.priority_dimension == "feedback quality"
    assert research.calls[1][0] == reviewed


def test_candidate_map_flow_does_not_wait_for_research_completion():
    research = FakeResearchAgent(
        [(_batch("alpha"), _summary(passed=1, branches=list(ResearchBranch)))],
    )
    decision_maker = FakeDecisionMaker(
        [_broad(), _complete()],
        delays=[0, 0.08],
    )
    budget = OrchestrationBudget(
        max_research_waves=2,
        max_targeted_enrichments=0,
        minimum_passed_candidates=2,
        minimum_branches_covered=4,
    )

    events = list(
        _orchestrator(
            research,
            decision_maker=decision_maker,
            budget=budget,
        ).stream(_brief())
    )
    event_types = [event.event for event in events]
    final_review_index = max(
        index
        for index, event_type in enumerate(event_types)
        if event_type == AgentEventType.COVERAGE_REVIEWED
    )

    assert event_types.index(AgentEventType.PRESENTATION_UPDATE) < final_review_index
    assert event_types.index(AgentEventType.PRESENTATION_UPDATE) < event_types.index(
        AgentEventType.ORCHESTRATION_COMPLETE
    )


def test_presentation_agent_cannot_mutate_deterministic_layout():
    research = FakeResearchAgent(
        [(_batch("alpha"), _summary(passed=1, branches=list(ResearchBranch)))]
    )
    budget = OrchestrationBudget(
        max_research_waves=1,
        max_targeted_enrichments=0,
        minimum_passed_candidates=1,
        minimum_branches_covered=1,
    )
    events = list(_orchestrator(research, budget=budget).stream(_brief()))
    update = next(event for event in events if event.event == AgentEventType.PRESENTATION_UPDATE)
    coordinates = [(node.node_id, node.x, node.y) for node in update.visualization_delta.upsert_nodes]

    update.presentation.node_labels["new"] = "Changed presentation only"

    assert [(node.node_id, node.x, node.y) for node in update.visualization_delta.upsert_nodes] == coordinates


def test_orchestration_budgets_prevent_unbounded_gap_fill_loops():
    research = FakeResearchAgent(
        [(_batch("alpha"), _summary(passed=0, branches=[ResearchBranch.DIRECT]))]
    )
    budget = OrchestrationBudget(
        max_research_waves=3,
        max_targeted_enrichments=2,
        minimum_passed_candidates=10,
        minimum_branches_covered=4,
    )

    decisions = [
        _broad(),
        OrchestratorDecision(
            action="FILL_GAP",
            target_branches=[ResearchBranch.ADJACENT],
        ),
        OrchestratorDecision(
            action="STRENGTHEN_NEAR_FIELD",
            target_branches=[ResearchBranch.DIRECT],
        ),
    ]
    orchestrator = _orchestrator(research, decisions=decisions, budget=budget)
    events = list(orchestrator.stream(_brief()))

    assert len(research.calls) == 3
    reviews = [event for event in events if event.event == AgentEventType.COVERAGE_REVIEWED]
    assert reviews[-1].orchestrator_decision.action == "COMPLETE"
    assert reviews[-1].orchestration_metrics.hard_stop
    assert reviews[-1].orchestration_metrics.hard_stop_code == "RESEARCH_BUDGET_EXHAUSTED"
    assert len(orchestrator.test_decision_maker.calls) == 3


def test_new_work_deadline_blocks_another_research_wave():
    research = FakeResearchAgent(
        [(_batch("alpha"), _summary(passed=1, branches=[ResearchBranch.DIRECT]))],
        pause_after_batch=0.04,
    )
    decision_maker = FakeDecisionMaker(
        [
            _broad(),
            OrchestratorDecision(
                action="FILL_GAP",
                target_branches=[ResearchBranch.ADJACENT],
            ),
        ]
    )
    budget = OrchestrationBudget(
        new_work_deadline_seconds=0.01,
        drain_grace_period_seconds=0.1,
    )

    events = list(
        _orchestrator(
            research,
            decision_maker=decision_maker,
            budget=budget,
        ).stream(_brief())
    )

    assert len(research.calls) == 1
    assert len(decision_maker.calls) == 1
    assert not any(event.error_code == "ORCHESTRATION_TIMEOUT" for event in events)
    assert events[-1].run_status == RunStatus.COMPLETE


def test_existing_presentation_drains_after_new_work_deadline():
    research = FakeResearchAgent(
        [(_batch("alpha"), _summary(passed=1, branches=list(ResearchBranch)))]
    )
    budget = OrchestrationBudget(
        max_research_waves=1,
        new_work_deadline_seconds=0.01,
        drain_grace_period_seconds=0.1,
    )

    events = list(
        _orchestrator(
            research,
            budget=budget,
            presentation=SlowPresentationAgent(0.03),
        ).stream(_brief())
    )

    assert AgentEventType.PRESENTATION_UPDATE in [event.event for event in events]
    assert not any(event.error_code == "ORCHESTRATION_TIMEOUT" for event in events)
    assert events[-1].run_status == RunStatus.COMPLETE


def test_absolute_hard_stop_emits_orchestration_timeout():
    research = FakeResearchAgent(
        [(_batch("alpha"), _summary(passed=1, branches=[ResearchBranch.DIRECT]))],
        pause_after_batch=0.08,
    )
    budget = OrchestrationBudget(
        new_work_deadline_seconds=0.01,
        drain_grace_period_seconds=0.01,
    )

    events = list(_orchestrator(research, budget=budget).stream(_brief()))

    timeout = next(
        event for event in events if event.error_code == "ORCHESTRATION_TIMEOUT"
    )
    assert timeout.event == AgentEventType.AGENT_DEGRADED
    assert "grace period" in timeout.message


def test_agent_failure_degrades_gracefully_and_emits_no_raw_exception():
    events = list(_orchestrator(FakeResearchAgent([], fail=True)).stream(_brief()))

    degraded = next(event for event in events if event.event == AgentEventType.AGENT_DEGRADED)
    assert degraded.error_code == "RESEARCH_AGENT_FAILED"
    assert "failed" in degraded.message.casefold()
    assert "RuntimeError" not in degraded.model_dump_json()
    assert events[-1].run_status == RunStatus.FAILED


def test_safe_agent_events_do_not_expose_chain_of_thought_or_strands_traces():
    research = FakeResearchAgent(
        [(_batch("alpha"), _summary(passed=1, branches=list(ResearchBranch)))]
    )
    budget = OrchestrationBudget(
        max_research_waves=1,
        minimum_passed_candidates=1,
        minimum_branches_covered=1,
    )

    serialized = json.dumps(
        [event.model_dump(mode="json") for event in _orchestrator(research, budget=budget).stream(_brief())]
    ).casefold()

    assert "chain_of_thought" not in serialized
    assert "raw_trace" not in serialized
    assert "strands_trace" not in serialized


class FakeAgent:
    def __init__(self, definition, tools):
        self.definition = definition
        self.tools = tools

    def as_tool(self, *, name, description):
        return {"agent_tool": name, "description": description}


class FakeStrandsFactory:
    def __init__(self):
        self.created = []
        self.models = []

    def function_tool(self, name, description, handler):
        return {"name": name, "description": description, "handler": handler}

    def create(self, definition, *, model, tools):
        agent = FakeAgent(definition, tools)
        self.created.append(agent)
        self.models.append(model)
        return agent


def test_strands_hierarchy_uses_specialists_as_bounded_tools():
    factory = FakeStrandsFactory()
    research = ResearchAgent.__new__(ResearchAgent)
    intelligence = MarketIntelligenceAgent(MarketIntelligenceService())

    agents = build_strands_agent_set(
        model="fake-model",
        research=research,
        intelligence=intelligence,
        factory=factory,
    )

    assert [agent.definition for agent in factory.created] == [
        MARKET_FRAMING_DEFINITION,
        RESEARCH_DEFINITION,
        INTELLIGENCE_DEFINITION,
        PRESENTATION_DEFINITION,
        ORCHESTRATOR_DEFINITION,
    ]
    assert factory.models == ["fake-model"] * 5
    assert [tool["agent_tool"] for tool in agents.orchestrator.tools] == [
        "invoke_research_agent",
        "invoke_market_intelligence_agent",
        "invoke_presentation_agent",
    ]
    assert [tool["name"] for tool in agents.research.tools] == ["run_parallel_research"]
    assert [tool["name"] for tool in agents.market_intelligence.tools] == [
        "analyze_research_batch"
    ]
    assert [tool["name"] for tool in agents.presentation.tools] == [
        "prepare_map_presentation"
    ]
    assert agents.decision_maker.agent is agents.orchestrator


def test_strands_builder_assigns_role_specific_models():
    factory = FakeStrandsFactory()
    models = {
        "framing": "fast-framing",
        "orchestrator": "reasoning-orchestrator",
        "research": "fast-research",
        "intelligence": "deep-intelligence",
        "presentation": "balanced-presentation",
    }

    build_strands_agent_set(
        model=models,
        research=ResearchAgent.__new__(ResearchAgent),
        intelligence=MarketIntelligenceAgent(MarketIntelligenceService()),
        factory=factory,
    )

    assert factory.models == [
        "fast-framing",
        "fast-research",
        "deep-intelligence",
        "balanced-presentation",
        "reasoning-orchestrator",
    ]


def test_strands_builder_requires_explicit_model_provider():
    try:
        build_strands_agent_set(
            model=None,
            research=ResearchAgent.__new__(ResearchAgent),
            intelligence=MarketIntelligenceAgent(MarketIntelligenceService()),
            factory=FakeStrandsFactory(),
        )
    except ValueError as error:
        assert "explicit Strands model provider" in str(error)
    else:
        raise AssertionError("builder should not fall back to implicit Bedrock")
