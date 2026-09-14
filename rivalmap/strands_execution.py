"""Typed Strands invocations used by the real Bedrock vertical slice."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .agents import PresentationAgent
from .contracts import (
    CandidateRecord,
    EnrichedProductProfile,
    EvidenceItem,
    MarketBrief,
    MarketModel,
    PresentationSections,
    ResearchPlan,
    SemanticProductAnalysis,
    StructuredProductFacts,
    VisualizationDelta,
)
from .market_intelligence import (
    ConservativeSemanticAnalyzer,
    ConservativeStructuredAnalyzer,
)
from .research import DeterministicResearchPlanner

OutputT = TypeVar("OutputT", bound=BaseModel)


class StructuredModelError(RuntimeError):
    """A model call failed or did not satisfy the required output schema."""


def invoke_structured(agent: Any, schema: type[OutputT], prompt: str) -> OutputT:
    try:
        result = agent(prompt, structured_output_model=schema)
        output = getattr(result, "structured_output", result)
        if isinstance(output, schema):
            return output
        return schema.model_validate(output)
    except (ValidationError, ValueError, TypeError, RuntimeError) as exc:
        raise StructuredModelError(f"Invalid {schema.__name__} model response") from exc
    except Exception as exc:
        raise StructuredModelError(f"{schema.__name__} model call failed") from exc


@dataclass(frozen=True)
class StrandsMarketBriefFramer:
    agent: Any

    def frame(
        self,
        product_idea: str,
        *,
        target_user: str | None,
        problem: str | None,
    ) -> MarketBrief:
        payload = {
            "product_idea": product_idea,
            "target_user": target_user,
            "problem": problem,
        }
        return invoke_structured(
            self.agent,
            MarketBrief,
            "Normalize the explicit user framing into a MarketBrief. Do not invent missing "
            f"facts. Input: {json.dumps(payload, sort_keys=True)}",
        )


@dataclass
class StrandsResearchPlanner:
    agent: Any
    fallback: DeterministicResearchPlanner = field(
        default_factory=DeterministicResearchPlanner
    )
    last_error: str | None = None

    def plan(self, brief: MarketBrief):
        try:
            plan = invoke_structured(
                self.agent,
                ResearchPlan,
                "Planning only: do not call tools. Generate one concise search query for each "
                "useful research branch. Keep the plan bounded in scope. Brief: "
                f"{brief.model_dump_json()}",
            )
        except StructuredModelError:
            self.last_error = "RESEARCH_MODEL_FAILED"
            return self.fallback.plan(brief)
        self.last_error = None
        return plan.seeds


@dataclass
class StrandsStructuredAnalyzer:
    agent: Any
    fallback: ConservativeStructuredAnalyzer = field(
        default_factory=ConservativeStructuredAnalyzer
    )
    last_error: str | None = None

    def analyze(
        self,
        candidate: CandidateRecord,
        evidence: list[EvidenceItem],
    ) -> StructuredProductFacts:
        prompt = (
            "Do not call tools. Extract only evidence-supported structured product facts. Cite "
            "evidence IDs and mark unknown fields as missing. "
            f"Candidate: {candidate.model_dump_json()} Evidence: "
            f"{json.dumps([item.model_dump(mode='json') for item in evidence], sort_keys=True)}"
        )
        try:
            result = invoke_structured(self.agent, StructuredProductFacts, prompt)
        except StructuredModelError:
            self.last_error = "STRUCTURED_MODEL_FAILED"
            return self.fallback.analyze(candidate, evidence)
        self.last_error = None
        return result


@dataclass
class StrandsSemanticAnalyzer:
    agent: Any
    fallback: ConservativeSemanticAnalyzer = field(
        default_factory=ConservativeSemanticAnalyzer
    )
    last_error: str | None = None

    def analyze(
        self,
        candidate: CandidateRecord,
        evidence: list[EvidenceItem],
        brief: MarketBrief,
    ) -> SemanticProductAnalysis:
        prompt = (
            "Do not call tools. Analyze relationship to the MarketBrief using only supplied "
            "evidence. Return DIRECT, ADJACENT, ALTERNATIVE, or UNKNOWN and cite evidence IDs. "
            f"Brief: {brief.model_dump_json()} Candidate: {candidate.model_dump_json()} Evidence: "
            f"{json.dumps([item.model_dump(mode='json') for item in evidence], sort_keys=True)}"
        )
        try:
            result = invoke_structured(self.agent, SemanticProductAnalysis, prompt)
        except StructuredModelError:
            self.last_error = "SEMANTIC_MODEL_FAILED"
            return self.fallback.analyze(candidate, evidence, brief)
        self.last_error = None
        return result


@dataclass
class StrandsPresentationAgent(PresentationAgent):
    agent: Any
    last_error: str | None = None

    def prepare(
        self,
        market_model: MarketModel,
        nodes_by_product: dict[str, Any],
        delta: VisualizationDelta,
    ) -> PresentationSections:
        deterministic = super().prepare(market_model, nodes_by_product, delta)
        payload = {
            "market_model": market_model.model_dump(mode="json"),
            "map_nodes": [
                node.model_dump(mode="json")
                for _, node in sorted(nodes_by_product.items())
            ],
            "clusters": [cluster.model_dump(mode="json") for cluster in delta.upsert_clusters],
            "focus_ring": [entry.model_dump(mode="json") for entry in delta.focus_ring or []],
            "deterministic_metadata": deterministic.model_dump(mode="json"),
        }
        try:
            result = invoke_structured(
                self.agent,
                PresentationSections,
                "Do not call tools. Create concise Closest Rivals, Your Differentiation, and "
                "Opportunity Around You copy. Preserve every supplied node label, callout, and "
                "Focus Ring member exactly. "
                f"Input: {json.dumps(payload, sort_keys=True)}",
            )
        except StructuredModelError:
            self.last_error = "PRESENTATION_MODEL_FAILED"
            return deterministic
        self.last_error = None
        result.node_labels = deterministic.node_labels
        result.callouts = deterministic.callouts
        return result


def profile_payload(profile: EnrichedProductProfile) -> dict[str, Any]:
    """Return the public typed profile payload without model traces."""

    return profile.model_dump(mode="json")
