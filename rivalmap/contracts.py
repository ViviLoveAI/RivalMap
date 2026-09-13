"""Framework-neutral contracts for RivalMap.

Copied/adapted from MarketCompass frozen baseline ca1356c. Keep these contracts
small and stable so MarketCompass can later call RivalMap as a capability.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, model_validator


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _now() -> datetime:
    return datetime.now(UTC)


class EvidenceRelation(StrEnum):
    SUPPORTS = "SUPPORTS"
    OPPOSES = "OPPOSES"
    CONTEXT = "CONTEXT"


class SourceQuality(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    AGGREGATOR = "AGGREGATOR"
    UNKNOWN = "UNKNOWN"


class DegradationLevel(StrEnum):
    FULL = "FULL"
    D1 = "D1"
    D2 = "D2"
    D3 = "D3"
    FAILED = "FAILED"


class RunStatus(StrEnum):
    """Externally observable run phase, independent of capability degradation."""

    STARTING = "STARTING"
    FRAMING = "FRAMING"
    RESEARCHING = "RESEARCHING"
    INITIAL_READY = "INITIAL_READY"
    ENRICHING = "ENRICHING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class ResearchBranch(StrEnum):
    DIRECT = "DIRECT"
    ADJACENT = "ADJACENT"
    CATEGORY = "CATEGORY"
    ALTERNATIVES = "ALTERNATIVES"


class ResearchEventType(StrEnum):
    CANDIDATE_FOUND = "candidate_found"
    CANDIDATE_VALIDATED = "candidate_validated"
    RESEARCH_BATCH_UPDATED = "research_batch_updated"
    RESEARCH_WAVE_COMPLETE = "research_wave_complete"


class IntelligenceEventType(StrEnum):
    ANALYSIS_STARTED = "analysis_started"
    STRUCTURED_ANALYSIS_COMPLETE = "structured_analysis_complete"
    SEMANTIC_ANALYSIS_COMPLETE = "semantic_analysis_complete"
    PRODUCT_PROFILE_READY = "product_profile_ready"
    ANALYSIS_PARTIAL = "analysis_partial"
    ANALYSIS_FAILED = "analysis_failed"


class RuntimeEventType(StrEnum):
    RUN_STARTED = "run_started"
    DISCOVERY_STARTED = "discovery_started"
    EVIDENCE_READY = "evidence_ready"
    STRUCTURE_READY = "structure_ready"
    BASE_MAP_READY = "base_map_ready"
    ANALYSIS_READY = "analysis_ready"
    RIVAL_MAP_READY = "rival_map_ready"
    RUN_FAILED = "run_failed"


class RivalMapRequest(BaseModel):
    idea: str = Field(min_length=1)
    target_user: str | None = None
    problem: str | None = None
    exclusions: list[str] = Field(default_factory=list)
    max_results: int = Field(default=6, ge=1, le=20)

    @property
    def query_text(self) -> str:
        parts = [self.idea, self.target_user or "", self.problem or ""]
        if self.exclusions:
            parts.append("exclude " + ", ".join(self.exclusions))
        return " ".join(part for part in parts if part).strip()


class SessionContext(BaseModel):
    product_idea: str = Field(min_length=1)
    target_user: str | None = None
    problem: str | None = None
    exclusions: list[str] = Field(default_factory=list)


class Source(BaseModel):
    source_id: str = Field(default_factory=lambda: _id("source"))
    url: HttpUrl
    title: str = ""
    quality: SourceQuality = SourceQuality.UNKNOWN
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=_now)


class EvidenceItem(BaseModel):
    evidence_id: str = Field(default_factory=lambda: _id("evidence"))
    topic: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    source: Source
    evidence_text: str = Field(min_length=1)
    relation: EvidenceRelation = EvidenceRelation.CONTEXT
    confidence: float = Field(ge=0, le=1)
    inferred: bool = False


class CompactEvidenceItem(BaseModel):
    evidence_id: str
    title: str
    url: HttpUrl
    claim: str
    text: str
    confidence: float


class MapDimension(BaseModel):
    name: str = Field(min_length=1)
    low_label: str = Field(min_length=1)
    high_label: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class ProductMapPoint(BaseModel):
    product_name: str = Field(min_length=1)
    x: float = Field(ge=0, le=10)
    y: float = Field(ge=0, le=10)
    segment: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    status: Literal["ACTIVE", "EXPLORED", "OPPORTUNITY"] = "ACTIVE"


class ProductMap(BaseModel):
    title: str = Field(min_length=1)
    x_axis: MapDimension
    y_axis: MapDimension
    points: list[ProductMapPoint] = Field(default_factory=list)
    map_summary: str = Field(min_length=1)


class ProductProfile(BaseModel):
    product_id: str = Field(default_factory=lambda: _id("product"))
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source_evidence_ids: list[str] = Field(default_factory=list)
    source_urls: list[HttpUrl] = Field(default_factory=list)
    directness: Literal["DIRECT", "ADJACENT", "UNKNOWN"] = "UNKNOWN"
    confidence: float = Field(default=0.5, ge=0, le=1)
    tags: list[str] = Field(default_factory=list)


class ProductRelation(BaseModel):
    relation_id: str = Field(default_factory=lambda: _id("relation"))
    source_product_id: str = Field(min_length=1)
    target_product_id: str = Field(min_length=1)
    relation_type: Literal["SIMILARITY"] = "SIMILARITY"
    score: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)


class MarketCluster(BaseModel):
    cluster_id: str = Field(default_factory=lambda: _id("cluster"))
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    product_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class ProductPosition(BaseModel):
    product_id: str = Field(min_length=1)
    x: float = Field(ge=0, le=10)
    y: float = Field(ge=0, le=10)
    cluster_id: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)


class MarketStructure(BaseModel):
    products: list[ProductProfile] = Field(default_factory=list)
    relations: list[ProductRelation] = Field(default_factory=list)
    clusters: list[MarketCluster] = Field(default_factory=list)
    positions: list[ProductPosition] = Field(default_factory=list)
    degradation_level: DegradationLevel = DegradationLevel.D3
    summary: str = Field(min_length=1)


class AnalysisResult(BaseModel):
    summary: str = Field(min_length=1)
    market_meaning: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)
    opportunity_hypotheses: list[str] = Field(default_factory=list)


class InterpretiveAnalysis(BaseModel):
    provider: str = "deterministic"
    summary: str = Field(min_length=1)
    market_meaning: list[str] = Field(default_factory=list)
    positioning_notes: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)
    opportunity_hypotheses: list[str] = Field(default_factory=list)
    available: bool = True


class CompetitorRanking(BaseModel):
    product_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    rank: int = Field(ge=1)
    rationale: str = Field(min_length=1)


class DimensionScore(BaseModel):
    product_id: str = Field(min_length=1)
    dimension: str = Field(min_length=1)
    score: float = Field(ge=0, le=10)
    rationale: str = Field(min_length=1)


class ComparisonFact(BaseModel):
    product_ids: list[str] = Field(min_length=1)
    dimension: str = Field(min_length=1)
    fact: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class StructuredComparison(BaseModel):
    provider: str = "deterministic"
    competitor_ranking: list[CompetitorRanking] = Field(default_factory=list)
    dimension_scores: list[DimensionScore] = Field(default_factory=list)
    cluster_labels: dict[str, str] = Field(default_factory=dict)
    comparison_facts: list[ComparisonFact] = Field(default_factory=list)
    available: bool = False


class MarketBrief(SessionContext):
    """V1 name for the structured scan context already represented by SessionContext."""


class SearchSeed(BaseModel):
    seed_id: str = Field(default_factory=lambda: _id("seed"))
    query: str = Field(min_length=1)
    branch: ResearchBranch = ResearchBranch.CATEGORY


class CandidateRecord(BaseModel):
    candidate_id: str = Field(default_factory=lambda: _id("candidate"))
    name: str = Field(min_length=1)
    description: str = ""
    source_evidence_ids: list[str] = Field(min_length=1)
    canonical_url: HttpUrl | None = None
    domain: str = ""
    name_variants: list[str] = Field(default_factory=list)


class CandidateValidation(BaseModel):
    candidate_id: str = Field(min_length=1)
    status: Literal["PASS", "PROVISIONAL", "REJECT"]
    reason: str | None = None
    source_evidence_ids: list[str] = Field(default_factory=list)
    is_product_or_company: bool
    relevance_score: float = Field(ge=0, le=1)
    identity_confidence: float = Field(ge=0, le=1)
    source_quality: SourceQuality = SourceQuality.UNKNOWN
    evidence_coverage: int = Field(ge=0)

    @model_validator(mode="after")
    def validation_has_support(self) -> CandidateValidation:
        if self.status == "PASS" and not self.source_evidence_ids:
            raise ValueError("PASS candidate validation requires supporting evidence")
        if self.status == "REJECT" and not self.reason:
            raise ValueError("REJECT candidate validation requires a reason")
        return self


class ResearchBatch(BaseModel):
    batch_id: str = Field(default_factory=lambda: _id("batch"))
    seed: SearchSeed
    seeds: list[SearchSeed] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    candidates: list[CandidateRecord] = Field(default_factory=list)
    validations: list[CandidateValidation] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_are_coherent(self) -> ResearchBatch:
        if not self.seeds:
            self.seeds = [self.seed]
        seed_ids = [item.seed_id for item in self.seeds]
        if len(seed_ids) != len(set(seed_ids)):
            raise ValueError("seed_id values must be unique within a research batch")
        if self.seed.seed_id not in seed_ids:
            raise ValueError("primary research seed must be included in seeds")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence_id values must be unique within a research batch")
        candidate_ids = [item.candidate_id for item in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate_id values must be unique within a research batch")
        missing = {
            evidence_id
            for candidate in self.candidates
            for evidence_id in candidate.source_evidence_ids
            if evidence_id not in evidence_ids
        }
        if missing:
            raise ValueError("candidate evidence references must exist in the research batch")
        validation_ids = [item.candidate_id for item in self.validations]
        if len(validation_ids) != len(set(validation_ids)):
            raise ValueError("candidate validations must be unique within a research batch")
        if set(validation_ids) != set(candidate_ids):
            raise ValueError("every research batch candidate requires one validation")
        if any(validation.status == "REJECT" for validation in self.validations):
            raise ValueError("rejected candidates cannot enter a research batch")
        candidate_by_id = {candidate.candidate_id: candidate for candidate in self.candidates}
        if any(
            not set(validation.source_evidence_ids).issubset(
                candidate_by_id[validation.candidate_id].source_evidence_ids
            )
            for validation in self.validations
        ):
            raise ValueError("candidate validation evidence must exist on the candidate")
        return self


class ResearchBudget(BaseModel):
    max_concurrent_searches: int = Field(default=4, ge=1, le=16)
    max_queries_per_wave: int = Field(default=4, ge=1, le=32)
    max_candidates_per_query: int = Field(default=6, ge=1, le=20)
    request_timeout_seconds: float = Field(default=8.0, gt=0, le=120)
    wave_timeout_seconds: float = Field(default=20.0, gt=0, le=300)


class ResearchSummary(BaseModel):
    candidates_found: int = Field(default=0, ge=0)
    passed: int = Field(default=0, ge=0)
    provisional: int = Field(default=0, ge=0)
    rejected: int = Field(default=0, ge=0)
    queries_completed: int = Field(default=0, ge=0)
    queries_failed: int = Field(default=0, ge=0)
    search_branches_covered: list[ResearchBranch] = Field(default_factory=list)
    research_continuing: bool = True


class ResearchEvent(BaseModel):
    event: ResearchEventType
    summary: ResearchSummary
    branch: ResearchBranch | None = None
    candidate: CandidateRecord | None = None
    validation: CandidateValidation | None = None
    batch: ResearchBatch | None = None
    error_code: Literal["TIMEOUT", "SEARCH_FAILED"] | None = None


class StructuredProductFacts(BaseModel):
    product_id: str = Field(min_length=1)
    product_name: str | None = None
    company_name: str | None = None
    canonical_url: HttpUrl | None = None
    positioning: str | None = None
    target_users: list[str] = Field(default_factory=list)
    product_category: str | None = None
    primary_use_case: str | None = None
    features: list[str] = Field(default_factory=list)
    workflow_coverage: list[str] = Field(default_factory=list)
    pricing_signals: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    business_model: str | None = None
    source_evidence_ids: list[str] = Field(min_length=1)
    field_evidence_ids: dict[str, list[str]] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0, le=1)
    missing_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def contains_a_product_fact(self) -> StructuredProductFacts:
        factual_values = (
            self.product_name,
            self.company_name,
            self.canonical_url,
            self.positioning,
            self.target_users,
            self.product_category,
            self.primary_use_case,
            self.features,
            self.workflow_coverage,
            self.pricing_signals,
            self.integrations,
            self.business_model,
        )
        if not any(factual_values):
            raise ValueError("structured product facts require at least one fact")
        cited = {
            evidence_id
            for evidence_ids in self.field_evidence_ids.values()
            for evidence_id in evidence_ids
        }
        if not cited.issubset(self.source_evidence_ids):
            raise ValueError("field evidence must be included in source_evidence_ids")
        return self


class SemanticProductAnalysis(BaseModel):
    product_id: str = Field(min_length=1)
    directness: Literal["DIRECT", "ADJACENT", "UNKNOWN"] = "UNKNOWN"
    relationship: Literal["DIRECT", "ADJACENT", "ALTERNATIVE", "UNKNOWN"] = "UNKNOWN"
    problem_solved: str | None = None
    core_workflow: str | None = None
    positioning: str | None = None
    relevance_to_brief: str = Field(min_length=1)
    differentiators: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    source_evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(default=0.5, ge=0, le=1)


class EnrichedProductProfile(ProductProfile):
    candidate_id: str | None = None
    structured_facts: StructuredProductFacts
    semantic_analysis: SemanticProductAnalysis | None = None
    candidate_validation: CandidateValidation | None = None
    analysis_status: Literal["COMPLETE", "PARTIAL"] = "COMPLETE"
    field_origins: dict[
        str,
        list[Literal["STRUCTURED", "SEMANTIC", "VALIDATION"]],
    ] = Field(default_factory=dict)
    uncertainties: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enrichment_matches_profile(self) -> EnrichedProductProfile:
        if self.structured_facts.product_id != self.product_id:
            raise ValueError("structured_facts product_id must match the profile")
        if self.semantic_analysis and self.semantic_analysis.product_id != self.product_id:
            raise ValueError("semantic_analysis product_id must match the profile")
        if (
            self.candidate_id
            and self.candidate_validation
            and self.candidate_validation.candidate_id != self.candidate_id
        ):
            raise ValueError("candidate_validation must match candidate_id")
        referenced = set(self.structured_facts.source_evidence_ids)
        if self.semantic_analysis:
            referenced.update(self.semantic_analysis.source_evidence_ids)
        if self.candidate_validation:
            referenced.update(self.candidate_validation.source_evidence_ids)
        if not referenced.issubset(self.source_evidence_ids):
            raise ValueError("product analysis evidence must be present on the profile")
        return self


class AnalysisBudget(BaseModel):
    max_concurrent_candidates: int = Field(default=4, ge=1, le=16)


class IntelligenceEvent(BaseModel):
    event: IntelligenceEventType
    candidate_id: str = Field(min_length=1)
    structured_facts: StructuredProductFacts | None = None
    semantic_analysis: SemanticProductAnalysis | None = None
    profile: EnrichedProductProfile | None = None
    failed_path: Literal["STRUCTURED", "SEMANTIC", "BOTH"] | None = None
    error_code: Literal["PROVIDER_FAILED", "INVALID_OUTPUT"] | None = None


class MarketModel(BaseModel):
    products: list[EnrichedProductProfile] = Field(default_factory=list)
    relations: list[ProductRelation] = Field(default_factory=list)
    clusters: list[MarketCluster] = Field(default_factory=list)
    closest_product_ids: list[str] = Field(default_factory=list)
    degradation_level: DegradationLevel = DegradationLevel.D3
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def references_known_products(self) -> MarketModel:
        product_ids = [product.product_id for product in self.products]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("product_id values must be unique within a market model")
        known = set(product_ids)
        referenced = {
            product_id
            for relation in self.relations
            for product_id in (relation.source_product_id, relation.target_product_id)
        }
        referenced.update(self.closest_product_ids)
        referenced.update(
            product_id for cluster in self.clusters for product_id in cluster.product_ids
        )
        if not referenced.issubset(known):
            raise ValueError("market model references unknown products")
        return self


class MapNode(BaseModel):
    node_id: str = Field(default_factory=lambda: _id("node"))
    candidate_id: str = Field(min_length=1)
    product_id: str | None = None
    label: str = Field(min_length=1)
    lifecycle: Literal["CANDIDATE", "ENRICHED", "ANALYZED"] = "CANDIDATE"
    x: float | None = Field(default=None, ge=0, le=10)
    y: float | None = Field(default=None, ge=0, le=10)
    cluster_id: str | None = None
    source_evidence_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def node_state_is_coherent(self) -> MapNode:
        if (self.x is None) != (self.y is None):
            raise ValueError("map node coordinates must be provided together")
        if self.lifecycle != "CANDIDATE" and self.product_id is None:
            raise ValueError("enriched or analyzed nodes require product_id")
        return self


class MapCluster(MarketCluster):
    """Visualization-facing cluster contract reusing MarketCluster fields."""


class VisualizationDelta(BaseModel):
    sequence: int = Field(ge=0)
    run_status: RunStatus
    degradation_level: DegradationLevel
    upsert_nodes: list[MapNode] = Field(default_factory=list)
    remove_node_ids: list[str] = Field(default_factory=list)
    upsert_clusters: list[MapCluster] = Field(default_factory=list)
    remove_cluster_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def upserts_and_removals_do_not_conflict(self) -> VisualizationDelta:
        upsert_node_ids = {node.node_id for node in self.upsert_nodes}
        if upsert_node_ids.intersection(self.remove_node_ids):
            raise ValueError("a map node cannot be upserted and removed in the same delta")
        upsert_cluster_ids = {cluster.cluster_id for cluster in self.upsert_clusters}
        if upsert_cluster_ids.intersection(self.remove_cluster_ids):
            raise ValueError("a map cluster cannot be upserted and removed in the same delta")
        return self


class ComparisonRequest(BaseModel):
    product_ids: list[str] = Field(min_length=2)
    dimensions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def products_are_distinct(self) -> ComparisonRequest:
        if len(self.product_ids) != len(set(self.product_ids)):
            raise ValueError("comparison product_ids must be unique")
        return self


class ComparisonView(BaseModel):
    request: ComparisonRequest
    products: list[EnrichedProductProfile] = Field(min_length=2)
    comparison: StructuredComparison
    summary: str = Field(min_length=1)
    source_evidence_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def comparison_matches_request(self) -> ComparisonView:
        product_ids = [product.product_id for product in self.products]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("comparison products must be unique")
        if set(product_ids) != set(self.request.product_ids):
            raise ValueError("comparison products must match the request")
        if not self.comparison.available:
            raise ValueError("comparison view requires an available structured comparison")
        product_evidence = {
            evidence_id
            for product in self.products
            for evidence_id in product.source_evidence_ids
        }
        if not set(self.source_evidence_ids).issubset(product_evidence):
            raise ValueError("comparison evidence must be present on compared products")
        return self


class RivalMapState(BaseModel):
    session: SessionContext
    evidence: list[EvidenceItem] = Field(default_factory=list)
    market_structure: MarketStructure | None = None
    base_map: ProductMap | None = None
    interpretive_analysis: InterpretiveAnalysis | None = None
    structured_comparison: StructuredComparison | None = None
    degradation_level: DegradationLevel = DegradationLevel.D3
    summary: str = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def map_requires_structure(self) -> RivalMapState:
        if self.base_map is not None and self.market_structure is None:
            raise ValueError("base_map requires market_structure")
        return self


class WorkingState(BaseModel):
    request: RivalMapRequest
    session: SessionContext
    evidence: list[EvidenceItem] = Field(default_factory=list)
    market_structure: MarketStructure | None = None
    base_map: ProductMap | None = None
    analysis: AnalysisResult | None = None
    rival_map_state: RivalMapState | None = None


class RuntimeEvent(BaseModel):
    event: RuntimeEventType
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class DiscoveryService(Protocol):
    def discover(self, request: RivalMapRequest) -> list[EvidenceItem]:
        """Return typed evidence for one bounded competitive-intelligence request."""


class AnalysisService(Protocol):
    def analyze(
        self,
        request: RivalMapRequest,
        evidence: list[EvidenceItem],
        structure: MarketStructure | None,
    ) -> AnalysisResult | None:
        """Return optional bounded analysis. Failure must not erase structure/base map."""
