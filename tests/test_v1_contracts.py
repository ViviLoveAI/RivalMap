import pytest
from pydantic import ValidationError

from rivalmap.contracts import (
    CandidateRecord,
    CandidateValidation,
    ComparisonRequest,
    ComparisonView,
    DegradationLevel,
    EnrichedProductProfile,
    EvidenceItem,
    EvidenceRelation,
    MapCluster,
    MapNode,
    MarketBrief,
    MarketModel,
    ProductRelation,
    ResearchBatch,
    RivalMapState,
    RunStatus,
    SearchSeed,
    SemanticProductAnalysis,
    Source,
    SourceQuality,
    StructuredComparison,
    StructuredProductFacts,
    VisualizationDelta,
)


def _evidence(evidence_id: str, product_name: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        topic=product_name,
        claim=f"{product_name} is a product.",
        source=Source(
            source_id=f"source-{evidence_id}",
            url=f"https://example.com/{product_name.lower()}",
            title=product_name,
            quality=SourceQuality.PRIMARY,
        ),
        evidence_text=f"Verified information about {product_name}.",
        relation=EvidenceRelation.SUPPORTS,
        confidence=0.9,
    )


def _profile(product_id: str, evidence_id: str) -> EnrichedProductProfile:
    return EnrichedProductProfile(
        product_id=product_id,
        name=product_id.title(),
        description=f"Profile for {product_id}",
        source_evidence_ids=[evidence_id],
        source_urls=[f"https://example.com/{product_id}"],
        directness="DIRECT",
        confidence=0.8,
        structured_facts=StructuredProductFacts(
            product_id=product_id,
            positioning="Interview practice",
            target_users=["job seekers"],
            features=["feedback"],
            source_evidence_ids=[evidence_id],
        ),
        semantic_analysis=SemanticProductAnalysis(
            product_id=product_id,
            directness="DIRECT",
            relevance_to_brief="Addresses the same use case.",
            differentiators=["feedback depth"],
            source_evidence_ids=[evidence_id],
        ),
    )


def _round_trip(model):
    return type(model).model_validate_json(model.model_dump_json())


def test_v1_contracts_round_trip_with_provenance_and_incremental_state():
    evidence = [_evidence("ev-a", "Alpha"), _evidence("ev-b", "Beta")]
    brief = MarketBrief(product_idea="Interview coach", target_user="job seekers")
    validations = [
        CandidateValidation(
            candidate_id=candidate_id,
            status="PASS",
            source_evidence_ids=[evidence_id],
            is_product_or_company=True,
            relevance_score=0.8,
            identity_confidence=0.9,
            source_quality=SourceQuality.PRIMARY,
            evidence_coverage=1,
        )
        for candidate_id, evidence_id in (
            ("candidate-a", "ev-a"),
            ("candidate-b", "ev-b"),
        )
    ]
    batch = ResearchBatch(
        batch_id="batch-1",
        seed=SearchSeed(seed_id="seed-1", query="AI interview coach competitors"),
        evidence=evidence,
        candidates=[
            CandidateRecord(
                candidate_id="candidate-a",
                name="Alpha",
                source_evidence_ids=["ev-a"],
            ),
            CandidateRecord(
                candidate_id="candidate-b",
                name="Beta",
                source_evidence_ids=["ev-b"],
            ),
        ],
        validations=validations,
    )
    validation = validations[0]
    profiles = [_profile("alpha", "ev-a"), _profile("beta", "ev-b")]
    market = MarketModel(
        products=profiles,
        relations=[
            ProductRelation(
                source_product_id="alpha",
                target_product_id="beta",
                score=0.75,
                rationale="Shared target user and workflow.",
            )
        ],
        closest_product_ids=["alpha", "beta"],
        degradation_level=DegradationLevel.D1,
        summary="Two close competitors are supported by evidence.",
    )
    node = MapNode(
        node_id="node-alpha",
        candidate_id="candidate-a",
        product_id="alpha",
        label="Alpha",
        lifecycle="ANALYZED",
        x=2.0,
        y=4.0,
        source_evidence_ids=["ev-a"],
    )
    cluster = MapCluster(
        cluster_id="cluster-1",
        name="Interview practice",
        description="Products focused on interview practice.",
        product_ids=["alpha", "beta"],
    )
    delta = VisualizationDelta(
        sequence=3,
        run_status=RunStatus.ENRICHING,
        degradation_level=DegradationLevel.D2,
        upsert_nodes=[node],
        upsert_clusters=[cluster],
    )
    request = ComparisonRequest(product_ids=["alpha", "beta"])
    view = ComparisonView(
        request=request,
        products=profiles,
        comparison=StructuredComparison(provider="test", available=True),
        summary="Alpha and Beta overlap on interview practice.",
        source_evidence_ids=["ev-a", "ev-b"],
    )

    for contract in (brief, batch, validation, market, node, cluster, delta, request, view):
        assert _round_trip(contract) == contract

    assert view.products[0].semantic_analysis.source_evidence_ids == ["ev-a"]
    assert batch.candidates[0].source_evidence_ids == ["ev-a"]


def test_run_status_and_degradation_are_independent_dimensions():
    assert [status.value for status in RunStatus] == [
        "STARTING",
        "FRAMING",
        "RESEARCHING",
        "INITIAL_READY",
        "ENRICHING",
        "COMPLETE",
        "FAILED",
    ]
    assert [level.value for level in DegradationLevel] == ["FULL", "D1", "D2", "D3", "FAILED"]

    completed_but_degraded = VisualizationDelta(
        sequence=4,
        run_status=RunStatus.COMPLETE,
        degradation_level=DegradationLevel.D2,
    )
    failed_without_overwriting_last_capability_level = VisualizationDelta(
        sequence=5,
        run_status=RunStatus.FAILED,
        degradation_level=DegradationLevel.D3,
    )

    assert completed_but_degraded.run_status == "COMPLETE"
    assert completed_but_degraded.degradation_level == "D2"
    assert failed_without_overwriting_last_capability_level.run_status == "FAILED"
    assert failed_without_overwriting_last_capability_level.degradation_level == "D3"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ResearchBatch(
            seed=SearchSeed(query="competitors"),
            evidence=[_evidence("ev-a", "Alpha")],
            candidates=[CandidateRecord(name="Beta", source_evidence_ids=["missing"])],
        ),
        lambda: CandidateValidation(
            candidate_id="candidate-a",
            status="PASS",
            is_product_or_company=True,
            relevance_score=0.8,
            identity_confidence=0.9,
            evidence_coverage=1,
        ),
        lambda: CandidateValidation(
            candidate_id="candidate-a",
            status="REJECT",
            is_product_or_company=False,
            relevance_score=0,
            identity_confidence=0.2,
            evidence_coverage=0,
        ),
        lambda: StructuredProductFacts(product_id="alpha", source_evidence_ids=["ev-a"]),
        lambda: MapNode(
            candidate_id="candidate-a",
            label="Alpha",
            x=1.0,
            source_evidence_ids=["ev-a"],
        ),
        lambda: MapNode(
            candidate_id="candidate-a",
            label="Alpha",
            lifecycle="ENRICHED",
            source_evidence_ids=["ev-a"],
        ),
        lambda: ComparisonRequest(product_ids=["alpha", "alpha"]),
    ],
)
def test_v1_contracts_reject_invalid_states(factory):
    with pytest.raises(ValidationError):
        factory()


def test_aggregate_contracts_reject_dangling_or_conflicting_references():
    with pytest.raises(ValidationError, match="product analysis evidence"):
        EnrichedProductProfile(
            product_id="alpha",
            name="Alpha",
            description="Profile for Alpha",
            source_evidence_ids=["ev-a"],
            structured_facts=StructuredProductFacts(
                product_id="alpha",
                positioning="Interview practice",
                source_evidence_ids=["ev-missing"],
            ),
        )

    with pytest.raises(ValidationError, match="unknown products"):
        MarketModel(
            products=[_profile("alpha", "ev-a")],
            closest_product_ids=["beta"],
            summary="Invalid market model.",
        )

    node = MapNode(
        node_id="node-alpha",
        candidate_id="candidate-a",
        label="Alpha",
        source_evidence_ids=["ev-a"],
    )
    with pytest.raises(ValidationError, match="upserted and removed"):
        VisualizationDelta(
            sequence=1,
            run_status=RunStatus.INITIAL_READY,
            degradation_level=DegradationLevel.D3,
            upsert_nodes=[node],
            remove_node_ids=["node-alpha"],
        )

    with pytest.raises(ValidationError, match="must match the request"):
        ComparisonView(
            request=ComparisonRequest(product_ids=["alpha", "beta"]),
            products=[_profile("alpha", "ev-a"), _profile("gamma", "ev-c")],
            comparison=StructuredComparison(provider="test", available=True),
            summary="Invalid comparison.",
            source_evidence_ids=["ev-a", "ev-c"],
        )


def test_current_rival_map_state_payload_is_backward_compatible():
    legacy_payload = {
        "session": {
            "product_idea": "Interview coach",
            "target_user": None,
            "problem": None,
            "exclusions": [],
        },
        "evidence": [],
        "market_structure": None,
        "base_map": None,
        "interpretive_analysis": None,
        "structured_comparison": None,
        "degradation_level": "D3",
        "summary": "No candidates yet.",
        "capabilities": [],
    }

    state = RivalMapState.model_validate(legacy_payload)

    assert state.model_dump(mode="json") == legacy_payload
    assert set(RivalMapState.model_fields) == set(legacy_payload)
