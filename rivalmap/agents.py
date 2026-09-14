"""Bounded Strands agent definitions around RivalMap's tested V1 services."""

from __future__ import annotations

import hashlib
import json
import queue
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import (
    AgentEvent,
    AgentEventType,
    ComparisonPresentation,
    ComparisonView,
    EnrichedProductProfile,
    IntelligenceEvent,
    IntelligenceEventType,
    MapCluster,
    MarketBrief,
    MarketModel,
    OrchestrationBudget,
    OrchestrationMetrics,
    OrchestratorDecision,
    PresentationSections,
    ResearchBatch,
    ResearchBranch,
    ResearchEvent,
    ResearchSummary,
    RunStatus,
    SearchSeed,
    VisualizationDelta,
)
from .market_intelligence import CandidateIntelligenceInput, MarketIntelligenceService
from .market_map import StableMarketMap
from .research import DeterministicResearchPlanner, ParallelResearchService


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    system_prompt: str
    tool_names: tuple[str, ...]


MARKET_FRAMING_DEFINITION = AgentDefinition(
    name="market_framing_agent",
    description="Progressively frames a product idea into a MarketBrief.",
    system_prompt=(
        "Ask one concise clarification question at a time. Capture the product problem and "
        "target customer first. Return structured updates only; never expose private reasoning."
    ),
    tool_names=("update_market_brief",),
)
RESEARCH_DEFINITION = AgentDefinition(
    name="research_agent",
    description="Runs bounded parallel market research using RivalMap's research service.",
    system_prompt=(
        "Choose only bounded direct, adjacent, category, or alternative research branches. "
        "Return a typed plan for planning requests; use the supplied tool only for explicit "
        "execution requests. Do not validate or analyze products yourself."
    ),
    tool_names=("run_parallel_research",),
)
INTELLIGENCE_DEFINITION = AgentDefinition(
    name="market_intelligence_agent",
    description="Interprets admitted candidate evidence using RivalMap market intelligence.",
    system_prompt=(
        "Return typed structured or semantic analysis for individual analysis requests; use the "
        "supplied intelligence tool only for explicit batch execution. Preserve evidence and do "
        "not perform similarity, clustering, layout, or Focus Ring selection."
    ),
    tool_names=("analyze_research_batch",),
)
PRESENTATION_DEFINITION = AgentDefinition(
    name="presentation_agent",
    description="Prepares labels and concise interpretation from an existing market map.",
    system_prompt=(
        "Return typed metadata for presentation-generation requests; use the supplied tool only "
        "for explicit existing-map packaging. Never invent or change coordinates, similarity "
        "values, clusters, or Focus Ring membership."
    ),
    tool_names=("prepare_map_presentation",),
)
ORCHESTRATOR_DEFINITION = AgentDefinition(
    name="orchestrator_agent",
    description="Makes bounded aggregate research-direction decisions.",
    system_prompt=(
        "Coordinate the specialist agents as tools using aggregate coverage and explicit budgets. "
        "Never approve candidates individually and never emit private reasoning or raw traces."
    ),
    tool_names=(
        "invoke_research_agent",
        "invoke_market_intelligence_agent",
        "invoke_presentation_agent",
    ),
)


class MarketFramingAgent:
    """Latency-sensitive deterministic framing state used before model-backed refinement."""

    def __init__(self) -> None:
        self.brief: MarketBrief | None = None
        self.pending_field: str | None = None
        self._exclusions_asked = False

    @property
    def research_ready(self) -> bool:
        return bool(self.brief and self.brief.problem and self.brief.target_user)

    def start(
        self,
        product_idea: str,
        *,
        problem: str | None = None,
        target_user: str | None = None,
    ) -> list[AgentEvent]:
        self.brief = MarketBrief(
            product_idea=product_idea,
            problem=problem,
            target_user=target_user,
        )
        events = [
            AgentEvent(
                event=AgentEventType.FRAMING_STARTED,
                run_status=RunStatus.FRAMING,
                message="Market framing started.",
                market_brief=self.brief,
            )
        ]
        question = self._next_question()
        if question:
            events.append(question)
        return events

    def answer(self, value: str) -> list[AgentEvent]:
        if self.brief is None or self.pending_field is None:
            raise ValueError("no framing question is awaiting an answer")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("framing answers cannot be empty")
        if self.pending_field == "exclusions":
            updated = self.brief.model_copy(update={"exclusions": [cleaned]})
        else:
            updated = self.brief.model_copy(update={self.pending_field: cleaned})
        self.brief = MarketBrief.model_validate(updated.model_dump())
        self.pending_field = None
        events = [
            AgentEvent(
                event=AgentEventType.MARKET_BRIEF_UPDATED,
                run_status=(RunStatus.RESEARCHING if self.research_ready else RunStatus.FRAMING),
                message="Market brief updated.",
                market_brief=self.brief,
            )
        ]
        question = self._next_question()
        if question:
            events.append(question)
        return events

    def _next_question(self) -> AgentEvent | None:
        assert self.brief is not None
        if not self.brief.problem:
            field = "problem"
            message = "What core problem should this product solve?"
        elif not self.brief.target_user:
            field = "target_user"
            message = "Who is the primary target customer?"
        elif not self._exclusions_asked:
            field = "exclusions"
            message = "Are there any products or categories to exclude?"
            self._exclusions_asked = True
        else:
            return None
        self.pending_field = field
        return AgentEvent(
            event=AgentEventType.FRAMING_QUESTION,
            run_status=(RunStatus.RESEARCHING if self.research_ready else RunStatus.FRAMING),
            message=message,
            market_brief=self.brief,
            question_field=field,
        )


class ResearchAgent:
    def __init__(self, service: ParallelResearchService, *, planner: Any | None = None) -> None:
        self.service = service
        self.planner = planner or DeterministicResearchPlanner()

    def stream(
        self,
        brief: MarketBrief,
        *,
        branches: Sequence[ResearchBranch] | None = None,
        wave: int = 1,
    ) -> Iterator[ResearchEvent]:
        seeds = None
        if branches is not None:
            selected = set(branches)
            seeds = []
            for seed in self.planner.plan(brief):
                if seed.branch not in selected:
                    continue
                query = (
                    seed.query
                    if wave == 1
                    else f"{seed.query} targeted follow-up wave {wave}"
                )
                digest = hashlib.sha256(f"{seed.branch.value}:{query}".encode()).hexdigest()[:16]
                seeds.append(
                    SearchSeed(seed_id=f"seed_{digest}", query=query, branch=seed.branch)
                )
        yield from self.service.stream(brief, seeds)


class MarketIntelligenceAgent:
    def __init__(self, service: MarketIntelligenceService) -> None:
        self.service = service

    def inputs_from_batch(self, batch: ResearchBatch) -> list[CandidateIntelligenceInput]:
        return self.service.inputs_from_batch(batch)

    def stream_candidate(
        self,
        brief: MarketBrief,
        item: CandidateIntelligenceInput,
    ) -> Iterator[IntelligenceEvent]:
        yield from self.service.stream(brief, [item])


class PresentationAgent:
    """Pure metadata adapter: it has no API capable of mutating map geometry."""

    def prepare(
        self,
        market_model: MarketModel,
        nodes_by_product: dict[str, Any],
        delta: VisualizationDelta,
    ) -> PresentationSections:
        profiles = {profile.product_id: profile for profile in market_model.products}
        focus_ids = [entry.product_id for entry in delta.focus_ring or []]
        closest = [profiles[product_id].name for product_id in focus_ids if product_id in profiles]
        differentiators = []
        opportunities = []
        for product_id in focus_ids[:3]:
            profile = profiles.get(product_id)
            if profile is None:
                continue
            if profile.semantic_analysis:
                differentiators.extend(profile.semantic_analysis.differentiators[:1])
            opportunities.extend(profile.uncertainties[:1])
        return PresentationSections(
            closest_rivals=closest,
            your_differentiation=list(dict.fromkeys(differentiators))[:3],
            opportunity_around_you=list(dict.fromkeys(opportunities))[:3],
            node_labels={
                product_id: node.label
                for product_id, node in sorted(nodes_by_product.items())
            },
            callouts={
                entry.product_id: list(entry.reasons)
                for entry in delta.focus_ring or []
            },
        )

    def prepare_comparison(self, view: ComparisonView) -> ComparisonPresentation:
        """Repackage an existing comparison without generating new comparison claims."""

        labels = [profile.name for profile in view.products]
        return ComparisonPresentation(
            title=" vs. ".join(labels),
            product_labels=labels,
            summary=view.summary,
            source_evidence_ids=view.source_evidence_ids,
        )


class OrchestratorDecisionMaker(Protocol):
    def decide(self, metrics: OrchestrationMetrics) -> OrchestratorDecision:
        """Choose research direction from aggregate metrics, never individual candidates."""


class HardBudgetGuard:
    """Enforce non-model safety limits and legal branch scopes."""

    def enforce(
        self,
        metrics: OrchestrationMetrics,
        proposed: OrchestratorDecision,
    ) -> OrchestratorDecision:
        if metrics.hard_stop or not metrics.framing_sufficient:
            return OrchestratorDecision(action="COMPLETE")
        if (
            proposed.action in {"STRENGTHEN_NEAR_FIELD", "FILL_GAP"}
            and metrics.remaining_targeted_enrichments == 0
        ):
            return OrchestratorDecision(action="COMPLETE")
        if proposed.action == "COMPLETE":
            return proposed
        if proposed.action == "STRENGTHEN_NEAR_FIELD":
            allowed = {ResearchBranch.DIRECT, ResearchBranch.ADJACENT}
        elif proposed.action == "FILL_GAP":
            allowed = set(metrics.missing_branches)
        else:
            allowed = set(ResearchBranch)
        branches = [
            branch for branch in proposed.target_branches if branch in allowed
        ]
        if not branches:
            return OrchestratorDecision(action="COMPLETE")
        return proposed.model_copy(update={"target_branches": branches})


@dataclass(frozen=True)
class StrandsOrchestratorDecisionMaker:
    """Use the actual Strands Orchestrator Agent for high-level decisions."""

    agent: Any

    def decide(self, metrics: OrchestrationMetrics) -> OrchestratorDecision:
        prompt = (
            "Choose exactly one orchestration action from the supplied aggregate metrics. "
            "Do not call specialist tools for this coverage review and do not provide reasoning. "
            f"Metrics: {metrics.model_dump_json()}"
        )
        result = self.agent(prompt, structured_output_model=OrchestratorDecision)
        structured = getattr(result, "structured_output", None)
        if isinstance(structured, OrchestratorDecision):
            return structured
        if isinstance(result, OrchestratorDecision):
            return result
        raise ValueError("Strands Orchestrator did not return a structured decision")


class ProgressiveOrchestratorAgent:
    """Runs service-backed specialists concurrently and emits only safe events."""

    def __init__(
        self,
        research: ResearchAgent,
        intelligence: MarketIntelligenceAgent,
        presentation: PresentationAgent | None = None,
        *,
        decision_maker: OrchestratorDecisionMaker,
        budget: OrchestrationBudget | None = None,
        hard_budget_guard: HardBudgetGuard | None = None,
    ) -> None:
        self.research = research
        self.intelligence = intelligence
        self.presentation = presentation or PresentationAgent()
        self.decision_maker = decision_maker
        self.budget = budget or OrchestrationBudget()
        self.hard_budget_guard = hard_budget_guard or HardBudgetGuard()

    def stream(
        self,
        brief: MarketBrief,
        *,
        brief_provider: Callable[[], MarketBrief] | None = None,
    ) -> Iterator[AgentEvent]:
        started = time.monotonic()
        output: queue.Queue[tuple[str, Any]] = queue.Queue()
        executor = ThreadPoolExecutor(
            max_workers=self.budget.max_active_analyses + 1,
            thread_name_prefix="rivalmap-agents",
        )
        market_map = StableMarketMap(brief)
        profiles: dict[str, EnrichedProductProfile] = {}
        scheduled_candidates: set[str] = set()
        observed_candidates: set[str] = set()
        observed_validations: dict[str, str] = {}
        pending_inputs: list[CandidateIntelligenceInput] = []
        active_candidates: set[str] = set()
        futures: set[Future[None]] = set()
        research_running = False
        research_finished = False
        decision_running = False
        orchestration_failed = False
        new_work_closed = False
        waves_started = 0
        enrichments_requested = 0
        completed_summary = ResearchSummary(research_continuing=True)
        aggregate = ResearchSummary(research_continuing=True)
        last_delta: VisualizationDelta | None = None

        def current_brief() -> MarketBrief:
            return brief_provider() if brief_provider is not None else brief

        def research_worker(branches: Sequence[ResearchBranch] | None, wave: int) -> None:
            try:
                for event in self.research.stream(current_brief(), branches=branches, wave=wave):
                    output.put(("research", event))
            except Exception:  # noqa: BLE001 - contain specialist failure
                output.put(("research_failure", None))
            finally:
                output.put(("research_done", None))

        def analysis_worker(item: CandidateIntelligenceInput) -> None:
            try:
                for event in self.intelligence.stream_candidate(current_brief(), item):
                    output.put(("intelligence", event))
            except Exception:  # noqa: BLE001 - contain specialist failure
                output.put(("intelligence_failure", item.candidate.candidate_id))

        def metrics() -> OrchestrationMetrics:
            elapsed = time.monotonic() - started
            latest_brief = current_brief()
            remaining_waves = max(self.budget.max_research_waves - waves_started, 0)
            remaining_enrichments = max(
                self.budget.max_targeted_enrichments - enrichments_requested,
                0,
            )
            focus_ring = last_delta.focus_ring if last_delta else []
            near_field_quality = (
                sum(entry.proximity_score for entry in focus_ring) / 3
                if focus_ring
                else 0.0
            )
            new_work_expired = elapsed >= self.budget.new_work_deadline_seconds
            return OrchestrationMetrics(
                research_summary=aggregate,
                framing_sufficient=bool(latest_brief.problem and latest_brief.target_user),
                near_field_quality=round(min(near_field_quality, 1.0), 6),
                target_passed_candidates=self.budget.minimum_passed_candidates,
                target_branches_covered=self.budget.minimum_branches_covered,
                elapsed_seconds=round(elapsed, 6),
                remaining_research_waves=remaining_waves,
                remaining_targeted_enrichments=remaining_enrichments,
                missing_branches=[
                    branch
                    for branch in ResearchBranch
                    if branch not in aggregate.search_branches_covered
                ],
                hard_stop=new_work_expired or remaining_waves == 0,
                hard_stop_code=(
                    "TIME_BUDGET_EXHAUSTED"
                    if new_work_expired
                    else "RESEARCH_BUDGET_EXHAUSTED"
                    if remaining_waves == 0
                    else None
                ),
                market_brief=latest_brief,
            )

        def decision_worker(snapshot: OrchestrationMetrics) -> None:
            try:
                proposed = self.decision_maker.decide(snapshot)
                output.put(("decision", (snapshot, proposed)))
            except Exception:  # noqa: BLE001 - contain model/agent failure
                output.put(("decision_failure", snapshot))

        def start_wave(branches: Sequence[ResearchBranch] | None) -> bool:
            nonlocal new_work_closed, research_running, waves_started
            if (
                time.monotonic() - started >= self.budget.new_work_deadline_seconds
                or waves_started >= self.budget.max_research_waves
            ):
                new_work_closed = True
                return False
            waves_started += 1
            research_running = True
            futures.add(executor.submit(research_worker, branches, waves_started))
            return True

        def start_analyses() -> None:
            while pending_inputs and len(active_candidates) < self.budget.max_active_analyses:
                item = pending_inputs.pop(0)
                candidate_id = item.candidate.candidate_id
                active_candidates.add(candidate_id)
                futures.add(executor.submit(analysis_worker, item))

        initial_metrics = metrics()
        try:
            initial_proposed = self.decision_maker.decide(initial_metrics)
        except Exception:  # noqa: BLE001 - contain model/agent failure
            executor.shutdown(wait=False, cancel_futures=True)
            yield AgentEvent(
                event=AgentEventType.AGENT_DEGRADED,
                run_status=RunStatus.FAILED,
                message="Strands Orchestrator failed before research started.",
                orchestration_metrics=initial_metrics,
                error_code="ORCHESTRATOR_AGENT_FAILED",
            )
            yield AgentEvent(
                event=AgentEventType.ORCHESTRATION_COMPLETE,
                run_status=RunStatus.FAILED,
                message="RivalMap orchestration complete.",
                market_brief=brief,
                research_summary=aggregate.model_copy(update={"research_continuing": False}),
            )
            return
        current_metrics = metrics()
        initial_decision = self.hard_budget_guard.enforce(
            current_metrics,
            initial_proposed,
        )
        yield AgentEvent(
            event=AgentEventType.COVERAGE_REVIEWED,
            run_status=RunStatus.STARTING,
            message=f"Strands Orchestrator selected {initial_decision.action}.",
            research_summary=aggregate,
            orchestration_metrics=current_metrics,
            orchestrator_decision=initial_decision,
        )
        if initial_decision.action == "COMPLETE":
            research_finished = True
        elif start_wave(initial_decision.target_branches):
            if initial_decision.action in {"STRENGTHEN_NEAR_FIELD", "FILL_GAP"}:
                enrichments_requested += 1
            yield AgentEvent(
                event=AgentEventType.RESEARCH_REQUESTED,
                run_status=RunStatus.RESEARCHING,
                message="Strands Orchestrator requested initial research.",
                market_brief=brief,
                orchestration_metrics=current_metrics,
                orchestrator_decision=initial_decision,
            )
        else:
            research_finished = True

        try:
            while (
                research_running
                or decision_running
                or not research_finished
                or active_candidates
                or pending_inputs
            ):
                futures = {future for future in futures if not future.done()}
                if (
                    research_finished
                    and not active_candidates
                    and not pending_inputs
                    and not futures
                ):
                    research_running = False
                    decision_running = False
                    break

                elapsed = time.monotonic() - started
                if (
                    elapsed >= self.budget.new_work_deadline_seconds
                    and not new_work_closed
                ):
                    new_work_closed = True
                    snapshot = metrics()
                    decision = self.hard_budget_guard.enforce(
                        snapshot,
                        OrchestratorDecision(action="COMPLETE"),
                    )
                    yield AgentEvent(
                        event=AgentEventType.COVERAGE_REVIEWED,
                        run_status=RunStatus.ENRICHING if profiles else RunStatus.RESEARCHING,
                        message="New research work stopped at the orchestration deadline.",
                        research_summary=aggregate,
                        orchestration_metrics=snapshot,
                        orchestrator_decision=decision,
                    )
                    if not research_running and not decision_running:
                        research_finished = True

                if elapsed >= self.budget.absolute_hard_stop_seconds:
                    try:
                        kind, payload = output.get_nowait()
                    except queue.Empty:
                        orchestration_failed = True
                        yield AgentEvent(
                            event=AgentEventType.AGENT_DEGRADED,
                            run_status=(
                                RunStatus.ENRICHING if profiles else RunStatus.FAILED
                            ),
                            message="Orchestration drain grace period exhausted.",
                            error_code="ORCHESTRATION_TIMEOUT",
                        )
                        break
                    if kind not in {
                        "research_done",
                        "research_failure",
                        "decision",
                        "decision_failure",
                    }:
                        orchestration_failed = True
                        yield AgentEvent(
                            event=AgentEventType.AGENT_DEGRADED,
                            run_status=(
                                RunStatus.ENRICHING if profiles else RunStatus.FAILED
                            ),
                            message="Orchestration drain grace period exhausted.",
                            error_code="ORCHESTRATION_TIMEOUT",
                        )
                        break
                else:
                    try:
                        kind, payload = output.get(timeout=0.02)
                    except queue.Empty:
                        continue

                if kind == "research":
                    event: ResearchEvent = payload
                    if event.candidate is not None:
                        observed_candidates.add(event.candidate.candidate_id)
                    if event.validation is not None:
                        observed_validations[event.validation.candidate_id] = (
                            event.validation.status
                        )
                    aggregate = _combine_wave_summary(completed_summary, event.summary)
                    if observed_candidates:
                        statuses = list(observed_validations.values())
                        aggregate = aggregate.model_copy(
                            update={
                                "candidates_found": len(observed_candidates),
                                "passed": statuses.count("PASS"),
                                "provisional": statuses.count("PROVISIONAL"),
                                "rejected": statuses.count("REJECT"),
                            }
                        )
                    yield AgentEvent(
                        event=AgentEventType.RESEARCH_PROGRESS,
                        run_status=RunStatus.RESEARCHING,
                        message=f"Research progress: {event.event.value}.",
                        research_summary=aggregate,
                        research_event=event,
                    )
                    if event.batch is not None:
                        for item in self.intelligence.inputs_from_batch(event.batch):
                            candidate_id = item.candidate.candidate_id
                            if candidate_id not in scheduled_candidates:
                                scheduled_candidates.add(candidate_id)
                                pending_inputs.append(item)
                        start_analyses()
                elif kind == "research_failure":
                    research_finished = True
                    orchestration_failed = True
                    yield AgentEvent(
                        event=AgentEventType.AGENT_DEGRADED,
                        run_status=RunStatus.ENRICHING if profiles else RunStatus.RESEARCHING,
                        message="Research agent failed; completed candidate work was preserved.",
                        error_code="RESEARCH_AGENT_FAILED",
                    )
                elif kind == "research_done":
                    research_running = False
                    if research_finished:
                        continue
                    if new_work_closed:
                        research_finished = True
                        continue
                    snapshot = metrics()
                    if snapshot.hard_stop:
                        output.put(
                            (
                                "decision",
                                (snapshot, OrchestratorDecision(action="COMPLETE")),
                            )
                        )
                    else:
                        decision_running = True
                        futures.add(executor.submit(decision_worker, snapshot))
                elif kind == "decision":
                    decision_running = False
                    _, proposed = payload
                    snapshot = metrics()
                    decision = self.hard_budget_guard.enforce(snapshot, proposed)
                    yield AgentEvent(
                        event=AgentEventType.COVERAGE_REVIEWED,
                        run_status=RunStatus.ENRICHING if profiles else RunStatus.RESEARCHING,
                        message=f"Strands Orchestrator selected {decision.action}.",
                        research_summary=aggregate,
                        orchestration_metrics=snapshot,
                        orchestrator_decision=decision,
                    )
                    if decision.action != "COMPLETE":
                        if not start_wave(decision.target_branches):
                            research_finished = True
                            continue
                        completed_summary = aggregate
                        if decision.action in {
                            "STRENGTHEN_NEAR_FIELD",
                            "FILL_GAP",
                        }:
                            enrichments_requested += 1
                            yield AgentEvent(
                                event=AgentEventType.ENRICHMENT_REQUESTED,
                                run_status=RunStatus.ENRICHING,
                                message=f"Strands Orchestrator requested {decision.action}.",
                                research_summary=aggregate,
                                orchestration_metrics=snapshot,
                                orchestrator_decision=decision,
                            )
                        else:
                            yield AgentEvent(
                                event=AgentEventType.RESEARCH_REQUESTED,
                                run_status=RunStatus.RESEARCHING,
                                message="Strands Orchestrator requested broader research.",
                                research_summary=aggregate,
                                orchestration_metrics=snapshot,
                                orchestrator_decision=decision,
                            )
                    else:
                        research_finished = True
                elif kind == "decision_failure":
                    decision_running = False
                    research_finished = True
                    orchestration_failed = True
                    yield AgentEvent(
                        event=AgentEventType.AGENT_DEGRADED,
                        run_status=RunStatus.ENRICHING if profiles else RunStatus.FAILED,
                        message="Strands Orchestrator failed during coverage review.",
                        orchestration_metrics=payload,
                        error_code="ORCHESTRATOR_AGENT_FAILED",
                    )
                elif kind == "intelligence":
                    event = payload
                    yield AgentEvent(
                        event=AgentEventType.INTELLIGENCE_PROGRESS,
                        run_status=RunStatus.ENRICHING,
                        message=f"Market intelligence progress: {event.event.value}.",
                        intelligence_event=event,
                    )
                    if event.event == IntelligenceEventType.PRODUCT_PROFILE_READY:
                        assert event.profile is not None
                        profiles[event.profile.product_id] = event.profile
                        active_candidates.discard(event.candidate_id)
                        start_analyses()
                        delta = market_map.update([event.profile])
                        last_delta = delta
                        market_model = _market_model(profiles, market_map.clusters, delta)
                        try:
                            presentation = self.presentation.prepare(
                                market_model,
                                market_map.nodes,
                                delta,
                            )
                        except Exception:  # noqa: BLE001 - map delta remains usable
                            yield AgentEvent(
                                event=AgentEventType.AGENT_DEGRADED,
                                run_status=delta.run_status,
                                message="Presentation agent failed; map geometry was preserved.",
                                visualization_delta=delta,
                                error_code="PRESENTATION_AGENT_FAILED",
                            )
                        else:
                            yield AgentEvent(
                                event=AgentEventType.PRESENTATION_UPDATE,
                                run_status=delta.run_status,
                                message="Progressive market map presentation updated.",
                                visualization_delta=delta,
                                presentation=presentation,
                            )
                    elif event.event == IntelligenceEventType.ANALYSIS_FAILED:
                        active_candidates.discard(event.candidate_id)
                        start_analyses()
                elif kind == "intelligence_failure":
                    active_candidates.discard(payload)
                    start_analyses()
                    yield AgentEvent(
                        event=AgentEventType.AGENT_DEGRADED,
                        run_status=RunStatus.ENRICHING,
                        message="Market intelligence agent failed for one candidate.",
                        error_code="INTELLIGENCE_AGENT_FAILED",
                    )
                futures = {future for future in futures if not future.done()}
        finally:
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

        yield AgentEvent(
            event=AgentEventType.ORCHESTRATION_COMPLETE,
            run_status=(
                RunStatus.FAILED if orchestration_failed and not profiles else RunStatus.COMPLETE
            ),
            message="RivalMap orchestration complete.",
            market_brief=brief,
            research_summary=aggregate.model_copy(update={"research_continuing": False}),
        )


def _combine_wave_summary(
    completed: ResearchSummary,
    current_wave: ResearchSummary,
) -> ResearchSummary:
    return ResearchSummary(
        candidates_found=completed.candidates_found + current_wave.candidates_found,
        passed=completed.passed + current_wave.passed,
        provisional=completed.provisional + current_wave.provisional,
        rejected=completed.rejected + current_wave.rejected,
        queries_completed=completed.queries_completed + current_wave.queries_completed,
        queries_failed=completed.queries_failed + current_wave.queries_failed,
        search_branches_covered=sorted(
            set(completed.search_branches_covered).union(
                current_wave.search_branches_covered
            ),
            key=lambda branch: list(ResearchBranch).index(branch),
        ),
        research_continuing=True,
    )


def _market_model(
    profiles: dict[str, EnrichedProductProfile],
    clusters: dict[str, MapCluster],
    delta: VisualizationDelta,
) -> MarketModel:
    focus_ids = [entry.product_id for entry in delta.focus_ring or []]
    return MarketModel(
        products=sorted(profiles.values(), key=lambda profile: profile.product_id),
        clusters=sorted(clusters.values(), key=lambda cluster: cluster.cluster_id),
        closest_product_ids=focus_ids,
        degradation_level=delta.degradation_level,
        summary=f"Progressive market map with {len(profiles)} analyzed products.",
    )


@dataclass(frozen=True)
class StrandsAgentSet:
    market_framing: Any
    orchestrator: Any
    research: Any
    market_intelligence: Any
    presentation: Any
    decision_maker: StrandsOrchestratorDecisionMaker


class StrandsFactory(Protocol):
    def create(
        self,
        definition: AgentDefinition,
        *,
        model: Any,
        tools: list[Any],
    ) -> Any: ...

    def function_tool(
        self,
        name: str,
        description: str,
        handler: Callable[..., Any],
    ) -> Any: ...


class NativeStrandsFactory:
    """Lazy SDK adapter so importing RivalMap never initializes Bedrock."""

    def create(
        self,
        definition: AgentDefinition,
        *,
        model: Any,
        tools: list[Any],
    ) -> Any:
        from strands import Agent

        return Agent(
            model=model,
            system_prompt=definition.system_prompt,
            tools=tools,
            callback_handler=None,
        )

    def function_tool(
        self,
        name: str,
        description: str,
        handler: Callable[..., Any],
    ) -> Any:
        from strands import tool

        return tool(name=name, description=description)(handler)


def build_strands_agent_set(
    *,
    model: Any,
    research: ResearchAgent,
    intelligence: MarketIntelligenceAgent,
    presentation: PresentationAgent | None = None,
    factory: StrandsFactory | None = None,
) -> StrandsAgentSet:
    """Build the bounded hierarchy; an injected model prevents implicit Bedrock use."""

    if model is None:
        raise ValueError("an explicit Strands model provider is required")
    factory = factory or NativeStrandsFactory()
    presentation = presentation or PresentationAgent()

    def role_model(role: str) -> Any:
        if isinstance(model, dict):
            if role not in model:
                raise ValueError(f"missing explicit Strands model for {role}")
            return model[role]
        return model

    def update_market_brief(
        product_idea: str,
        problem: str = "",
        target_user: str = "",
    ) -> dict[str, Any]:
        """Create a validated market brief from explicitly supplied framing fields."""
        brief = MarketBrief(
            product_idea=product_idea,
            problem=problem or None,
            target_user=target_user or None,
        )
        return brief.model_dump(mode="json")

    def run_parallel_research(brief_json: str) -> str:
        """Run the existing bounded parallel research service and return its aggregate summary."""
        brief = MarketBrief.model_validate_json(brief_json)
        final = list(research.stream(brief))[-1]
        return final.summary.model_dump_json()

    def analyze_research_batch(brief_json: str, batch_json: str) -> str:
        """Run existing parallel intelligence analysis for an admitted research batch."""
        brief = MarketBrief.model_validate_json(brief_json)
        batch = ResearchBatch.model_validate_json(batch_json)
        events = []
        for item in intelligence.inputs_from_batch(batch):
            events.extend(intelligence.stream_candidate(brief, item))
        profiles = [
            event.profile.model_dump(mode="json")
            for event in events
            if event.profile is not None
        ]
        return json.dumps({"profiles": profiles}, sort_keys=True)

    def prepare_map_presentation(
        model_json: str,
        delta_json: str,
        comparison_json: str = "",
    ) -> str:
        """Prepare labels and interpretation without changing deterministic map fields."""
        market_model = MarketModel.model_validate_json(model_json)
        delta = VisualizationDelta.model_validate_json(delta_json)
        nodes = {
            node.product_id: node for node in delta.upsert_nodes if node.product_id is not None
        }
        result: dict[str, Any] = {
            "map": presentation.prepare(market_model, nodes, delta).model_dump(mode="json")
        }
        if comparison_json:
            view = ComparisonView.model_validate_json(comparison_json)
            result["comparison"] = presentation.prepare_comparison(view).model_dump(
                mode="json"
            )
        return json.dumps(result, sort_keys=True)

    framing_tool = factory.function_tool(
        "update_market_brief",
        "Validate explicit product framing fields as a MarketBrief.",
        update_market_brief,
    )
    research_tool = factory.function_tool(
        "run_parallel_research",
        "Invoke RivalMap's bounded ParallelResearchService.",
        run_parallel_research,
    )
    intelligence_tool = factory.function_tool(
        "analyze_research_batch",
        "Invoke RivalMap's parallel MarketIntelligenceService.",
        analyze_research_batch,
    )
    presentation_tool = factory.function_tool(
        "prepare_map_presentation",
        "Prepare metadata from an immutable deterministic map delta.",
        prepare_map_presentation,
    )
    framing_agent = factory.create(
        MARKET_FRAMING_DEFINITION,
        model=role_model("framing"),
        tools=[framing_tool],
    )
    research_agent = factory.create(
        RESEARCH_DEFINITION,
        model=role_model("research"),
        tools=[research_tool],
    )
    intelligence_agent = factory.create(
        INTELLIGENCE_DEFINITION,
        model=role_model("intelligence"),
        tools=[intelligence_tool],
    )
    presentation_agent = factory.create(
        PRESENTATION_DEFINITION,
        model=role_model("presentation"),
        tools=[presentation_tool],
    )
    specialist_tools = [
        research_agent.as_tool(
            name="invoke_research_agent",
            description=RESEARCH_DEFINITION.description,
        ),
        intelligence_agent.as_tool(
            name="invoke_market_intelligence_agent",
            description=INTELLIGENCE_DEFINITION.description,
        ),
        presentation_agent.as_tool(
            name="invoke_presentation_agent",
            description=PRESENTATION_DEFINITION.description,
        ),
    ]
    orchestrator = factory.create(
        ORCHESTRATOR_DEFINITION,
        model=role_model("orchestrator"),
        tools=specialist_tools,
    )
    return StrandsAgentSet(
        market_framing=framing_agent,
        orchestrator=orchestrator,
        research=research_agent,
        market_intelligence=intelligence_agent,
        presentation=presentation_agent,
        decision_maker=StrandsOrchestratorDecisionMaker(orchestrator),
    )
