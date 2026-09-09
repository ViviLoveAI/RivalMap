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
