import math

from rivalmap.contracts import (
    CandidateValidation,
    EnrichedProductProfile,
    MarketBrief,
    RunStatus,
    SemanticProductAnalysis,
    SourceQuality,
    StructuredProductFacts,
)
from rivalmap.market_map import StableMarketMap
from rivalmap.similarity import (
    FixedProjection2D,
    FocusRingSelector,
    ProductRepresentationBuilder,
    SimilarityEngine,
    semantic_relationship,
)


def _brief() -> MarketBrief:
    return MarketBrief(
        product_idea="AI interview coaching platform",
        target_user="job seekers",
        problem="practice interviews and receive feedback",
    )


def _profile(
    product_id: str,
    *,
    relationship="DIRECT",
    category="Interview coaching",
    target_users=None,
    problem="Practice interviews and improve answers",
    workflow="Practice interview receive feedback retry",
    features=None,
    confidence=0.85,
    evidence_coverage=3,
    source_quality=SourceQuality.PRIMARY,
    missing_fields=None,
    analysis_status="COMPLETE",
    legacy_directness="UNKNOWN",
) -> EnrichedProductProfile:
    evidence_id = f"ev-{product_id}"
    target_users = target_users or ["job seekers"]
    features = features or ["interview practice", "answer feedback"]
    missing_fields = missing_fields or []
    return EnrichedProductProfile(
        product_id=product_id,
        candidate_id=f"candidate-{product_id}",
        name=product_id.title(),
        description=problem,
        source_evidence_ids=[evidence_id],
        source_urls=[f"https://{product_id}.example"],
        directness=legacy_directness,
        confidence=confidence,
        structured_facts=StructuredProductFacts(
            product_id=product_id,
            product_name=product_id.title(),
            target_users=target_users,
            product_category=category,
            primary_use_case=problem,
            features=features,
            workflow_coverage=[workflow],
            positioning="AI-assisted practice",
            source_evidence_ids=[evidence_id],
            confidence=confidence,
            missing_fields=missing_fields,
        ),
        semantic_analysis=SemanticProductAnalysis(
            product_id=product_id,
            directness=legacy_directness,
            relationship=relationship,
            problem_solved=problem,
            core_workflow=workflow,
            positioning="Interview coaching",
            relevance_to_brief="Addresses interview preparation.",
            differentiators=features,
            source_evidence_ids=[evidence_id],
            confidence=confidence,
        ),
        candidate_validation=CandidateValidation(
            candidate_id=f"candidate-{product_id}",
            status="PASS" if source_quality != SourceQuality.AGGREGATOR else "PROVISIONAL",
            reason="Test fixture.",
            source_evidence_ids=[evidence_id],
            is_product_or_company=True,
            relevance_score=0.8,
            identity_confidence=confidence,
            source_quality=source_quality,
            evidence_coverage=evidence_coverage,
        ),
        analysis_status=analysis_status,
    )


def _product_nodes(delta):
    return [node for node in delta.upsert_nodes if node.node_type == "PRODUCT"]


def _radius(node) -> float:
    return math.dist((5.0, 5.0), (node.x, node.y))


def test_user_is_fixed_at_center_and_closer_product_has_smaller_radius():
    close = _profile("close")
    far = _profile(
        "far",
        relationship="ALTERNATIVE",
        category="Warehouse inventory",
        target_users=["logistics teams"],
        problem="Track warehouse stock",
        workflow="Scan inventory reconcile shipments",
        features=["barcode scanning", "stock alerts"],
    )
    delta = StableMarketMap(_brief()).update([far, close])
    user = next(node for node in delta.upsert_nodes if node.node_type == "USER_IDEA")
    nodes = {node.product_id: node for node in _product_nodes(delta)}

    assert (user.x, user.y) == (5.0, 5.0)
    assert user.similarity_to_user == 1.0
    assert _radius(nodes["close"]) < _radius(nodes["far"])


def test_semantic_relationship_is_authoritative_over_legacy_directness():
    alternative = _profile(
        "alternative",
        relationship="ALTERNATIVE",
        legacy_directness="DIRECT",
    )
    builder = ProductRepresentationBuilder()
    representation = builder.for_product(alternative)
    delta = StableMarketMap(_brief(), initial_ready_count=1).update([alternative])
    node = _product_nodes(delta)[0]

    assert semantic_relationship(alternative) == "ALTERNATIVE"
    assert representation.relationship == "ALTERNATIVE"
    assert node.relationship == "ALTERNATIVE"
    assert "ALTERNATIVE_RELATIONSHIP" in delta.focus_ring[0].reasons


def test_relationship_classification_does_not_change_geometric_similarity():
    builder = ProductRepresentationBuilder()
    engine = SimilarityEngine()
    projection = FixedProjection2D()
    user = builder.for_brief(_brief())
    direct = builder.for_product(_profile("direct", relationship="DIRECT"))
    alternative = builder.for_product(
        _profile("alternative", relationship="ALTERNATIVE")
    )

    direct_similarity = engine.compare_to_user(direct, user)
    alternative_similarity = engine.compare_to_user(alternative, user)

    assert direct_similarity.overall == alternative_similarity.overall
    assert direct_similarity.dimension_scores == alternative_similarity.dimension_scores
    assert projection.project(direct) == projection.project(alternative)


def test_product_product_similarity_is_higher_for_shared_market_features():
    builder = ProductRepresentationBuilder()
    engine = SimilarityEngine()
    first = builder.for_product(_profile("first"))
    similar = builder.for_product(_profile("similar", relationship="ADJACENT"))
    different = builder.for_product(
        _profile(
            "different",
            category="Warehouse inventory",
            target_users=["logistics teams"],
            problem="Track warehouse stock",
            workflow="Scan stock reconcile shipments",
            features=["barcodes", "stock alerts"],
        )
    )

    assert engine.compare_products(first, similar).overall > engine.compare_products(
        first, different
    ).overall


def test_shared_market_features_produce_closer_geometric_positions():
    first = _profile("first")
    similar = _profile("similar", relationship="ADJACENT")
    different = _profile(
        "different",
        relationship="ALTERNATIVE",
        category="Warehouse inventory",
        target_users=["logistics teams"],
        problem="Track warehouse stock",
        workflow="Scan stock reconcile shipments",
        features=["barcodes", "stock alerts"],
    )
    market_map = StableMarketMap(_brief())
    market_map.update([different, similar, first])
    nodes = market_map.nodes

    similar_distance = math.dist(
        (nodes["first"].x, nodes["first"].y),
        (nodes["similar"].x, nodes["similar"].y),
    )
    different_distance = math.dist(
        (nodes["first"].x, nodes["first"].y),
        (nodes["different"].x, nodes["different"].y),
    )
    assert similar_distance < different_distance


def test_direct_rival_outranks_equivalent_adjacent_rival_in_focus_ring():
    direct = _profile("direct", relationship="DIRECT")
    adjacent = _profile("adjacent", relationship="ADJACENT")
    builder = ProductRepresentationBuilder()
    engine = SimilarityEngine()
    user = builder.for_brief(_brief())
    similarities = {
        profile.product_id: engine.compare_to_user(builder.for_product(profile), user)
        for profile in (direct, adjacent)
    }

    ring = FocusRingSelector().select([adjacent, direct], similarities)

    assert [entry.product_id for entry in ring] == ["direct", "adjacent"]
    assert "DIRECT_RELATIONSHIP" in ring[0].reasons


def test_weak_evidence_candidate_does_not_dominate_focus_ring():
    weak = _profile(
        "weak",
        relationship="DIRECT",
        confidence=0.36,
        evidence_coverage=1,
        source_quality=SourceQuality.AGGREGATOR,
        missing_fields=["pricing", "integrations", "business_model", "target_users"],
        analysis_status="PARTIAL",
    )
    strong = _profile(
        "strong",
        relationship="ADJACENT",
        confidence=0.95,
        evidence_coverage=3,
    )
    builder = ProductRepresentationBuilder()
    engine = SimilarityEngine()
    user = builder.for_brief(_brief())
    similarities = {
        profile.product_id: engine.compare_to_user(builder.for_product(profile), user)
        for profile in (weak, strong)
    }

    ring = FocusRingSelector().select([weak, strong], similarities)

    assert ring[0].product_id == "strong"
    assert "STRONG_EVIDENCE" in ring[0].reasons
    weak_entry = next(entry for entry in ring if entry.product_id == "weak")
    assert "EVIDENCE_LIMITED" in weak_entry.reasons


def test_focus_ring_selection_is_stable_and_order_independent():
    profiles = [
        _profile("alpha", relationship="DIRECT"),
        _profile("beta", relationship="ADJACENT"),
        _profile("gamma", relationship="ALTERNATIVE"),
    ]
    builder = ProductRepresentationBuilder()
    engine = SimilarityEngine()
    user = builder.for_brief(_brief())
    similarities = {
        profile.product_id: engine.compare_to_user(builder.for_product(profile), user)
        for profile in profiles
    }
    selector = FocusRingSelector()

    assert selector.select(profiles, similarities) == selector.select(
        list(reversed(profiles)), similarities
    )


def test_incremental_addition_preserves_existing_coordinates():
    initial = [_profile("alpha"), _profile("beta"), _profile("gamma")]
    market_map = StableMarketMap(_brief())
    first = market_map.update(initial)
    original_positions = {
        node.product_id: (node.x, node.y) for node in _product_nodes(first)
    }

    second = market_map.update([_profile("delta", relationship="ADJACENT")])

    assert [node.product_id for node in _product_nodes(second)] == ["delta"]
    assert {
        product_id: (node.x, node.y)
        for product_id, node in market_map.nodes.items()
        if product_id in original_positions
    } == original_positions
    assert second.sequence == 1


def test_layout_is_deterministic_for_order_independent_initial_set():
    profiles = [_profile("alpha"), _profile("beta"), _profile("gamma")]
    first_map = StableMarketMap(_brief())
    second_map = StableMarketMap(_brief())

    first_map.update(profiles)
    second_map.update(list(reversed(profiles)))

    assert {
        product_id: (node.x, node.y, node.cluster_id)
        for product_id, node in first_map.nodes.items()
    } == {
        product_id: (node.x, node.y, node.cluster_id)
        for product_id, node in second_map.nodes.items()
    }
    assert first_map.product_similarities == second_map.product_similarities
    assert first_map.clusters == second_map.clusters


def test_collision_avoidance_separates_identical_representations():
    profiles = [_profile(f"copy-{index}") for index in range(8)]
    market_map = StableMarketMap(_brief())
    market_map.update(profiles)
    points = [(node.x, node.y) for node in market_map.nodes.values()]

    for index, point in enumerate(points):
        for other in points[index + 1 :]:
            assert math.dist(point, other) >= 0.419


def test_clusters_have_stable_membership_centroids_and_label_sources():
    interview_a = _profile("interview-a", category="Interview Coaching")
    interview_b = _profile("interview-b", category=" interview   coaching ")
    inventory = _profile(
        "inventory",
        category="Warehouse Inventory",
        target_users=["operations teams"],
    )
    market_map = StableMarketMap(_brief())
    delta = market_map.update([inventory, interview_b, interview_a])

    assert len(delta.upsert_clusters) == 2
    interview_cluster = next(
        cluster
        for cluster in delta.upsert_clusters
        if cluster.normalized_label == "interview coaching"
    )
    assert interview_cluster.product_ids == ["interview-a", "interview-b"]
    assert interview_cluster.label_source == "STRUCTURED_CATEGORY"
    assert interview_cluster.centroid_x is not None
    assert interview_cluster.centroid_y is not None
    assert interview_cluster.region_radius >= 0.3

    reversed_map = StableMarketMap(_brief())
    reversed_map.update([interview_a, interview_b, inventory])
    assert market_map.clusters == reversed_map.clusters


def test_visualization_delta_and_progressive_initial_ready_transition():
    market_map = StableMarketMap(_brief(), initial_ready_count=3)

    first = market_map.update([_profile("alpha")])
    second = market_map.update([_profile("beta")])
    third = market_map.update([_profile("gamma")])
    fourth = market_map.update([_profile("delta")])

    assert first.run_status == RunStatus.ENRICHING
    assert second.run_status == RunStatus.ENRICHING
    assert third.run_status == RunStatus.INITIAL_READY
    assert fourth.run_status == RunStatus.ENRICHING
    assert [first.sequence, second.sequence, third.sequence, fourth.sequence] == [0, 1, 2, 3]
    assert any(node.node_type == "USER_IDEA" for node in first.upsert_nodes)
    assert all(node.node_type == "PRODUCT" for node in second.upsert_nodes)
    assert third.focus_ring is not None
    assert [entry.rank for entry in third.focus_ring] == list(
        range(1, len(third.focus_ring) + 1)
    )
