"""Merge structure, base map, and optional analysis into RivalMapState."""

from __future__ import annotations

from .contracts import (
    AnalysisResult,
    DegradationLevel,
    EvidenceItem,
    InterpretiveAnalysis,
    MarketStructure,
    ProductMap,
    RivalMapState,
    SessionContext,
    StructuredComparison,
)


def interpretive_from_analysis(analysis: AnalysisResult | None) -> InterpretiveAnalysis | None:
    if analysis is None:
        return None
    return InterpretiveAnalysis(
        provider="deterministic",
        summary=analysis.summary,
        market_meaning=analysis.market_meaning,
        differentiators=analysis.differentiators,
        opportunity_hypotheses=analysis.opportunity_hypotheses,
        available=True,
    )


def deterministic_structured_comparison(
    structure: MarketStructure | None,
) -> StructuredComparison | None:
    if structure is None or not structure.products:
        return None
    return StructuredComparison(
        provider="deterministic",
        cluster_labels={cluster.cluster_id: cluster.name for cluster in structure.clusters},
        available=False,
    )


def resolve_degradation_level(
    *,
    structure: MarketStructure | None,
    base_map: ProductMap | None,
    interpretive: InterpretiveAnalysis | None,
    structured: StructuredComparison | None,
) -> DegradationLevel:
    if structure is None or not structure.products:
        return DegradationLevel.FAILED
    if base_map is None:
        return DegradationLevel.D3
    has_interpretive = bool(interpretive and interpretive.available)
    has_structured = bool(structured and structured.available)
    if has_interpretive and has_structured:
        return DegradationLevel.FULL
    if has_interpretive or has_structured:
        return DegradationLevel.D1
    return DegradationLevel.D2


def merge_rival_map_state(
    *,
    session: SessionContext,
    evidence: list[EvidenceItem],
    market_structure: MarketStructure | None,
    base_map: ProductMap | None,
    analysis: AnalysisResult | None,
    structured_comparison: StructuredComparison | None = None,
) -> RivalMapState:
    interpretive = interpretive_from_analysis(analysis)
    structured = structured_comparison or deterministic_structured_comparison(market_structure)
    level = resolve_degradation_level(
        structure=market_structure,
        base_map=base_map,
        interpretive=interpretive,
        structured=structured,
    )
    if market_structure is None or not market_structure.products:
        summary = "还没有足够候选产品形成地图。"
    elif analysis is not None:
        summary = analysis.summary
    else:
        summary = market_structure.summary

    capabilities = ["evidence"]
    if market_structure is not None:
        capabilities.append("market_structure")
    if base_map is not None:
        capabilities.append("base_map")
    if interpretive and interpretive.available:
        capabilities.append("interpretive_analysis")
    if structured and structured.available:
        capabilities.append("structured_comparison")

    return RivalMapState(
        session=session,
        evidence=evidence,
        market_structure=market_structure,
        base_map=base_map,
        interpretive_analysis=interpretive,
        structured_comparison=structured,
        degradation_level=level,
        summary=summary,
        capabilities=capabilities,
    )
