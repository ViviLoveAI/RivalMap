"""Stable incremental market geometry centered on the user's product idea."""

from __future__ import annotations

import hashlib
import math

from .contracts import (
    DegradationLevel,
    EnrichedProductProfile,
    MapCluster,
    MapNode,
    MarketBrief,
    RunStatus,
    SimilarityResult,
    VisualizationDelta,
)
from .similarity import (
    FeatureRepresentation,
    FixedProjection2D,
    FocusRingSelector,
    ProductRepresentationBuilder,
    SimilarityEngine,
    semantic_relationship,
)

_CENTER = (5.0, 5.0)
_MIN_RADIUS = 0.9
_MAX_RADIUS = 4.1
_MIN_NODE_DISTANCE = 0.42


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _normalized_label(value: str) -> str:
    return " ".join(value.casefold().split())


def _cluster_label(profile: EnrichedProductProfile) -> tuple[str, str, str]:
    category = profile.structured_facts.product_category
    if category and category.strip():
        display = " ".join(category.split())
        return display, _normalized_label(display), "STRUCTURED_CATEGORY"
    return "Uncategorized", "uncategorized", "FALLBACK"


class StableMarketMap:
    """Stateful projector that never refits existing node coordinates."""

    def __init__(
        self,
        brief: MarketBrief,
        *,
        initial_ready_count: int = 3,
        representation_builder: ProductRepresentationBuilder | None = None,
        similarity_engine: SimilarityEngine | None = None,
        projection: FixedProjection2D | None = None,
        focus_selector: FocusRingSelector | None = None,
    ) -> None:
        if initial_ready_count < 1:
            raise ValueError("initial_ready_count must be positive")
        self.brief = brief
        self.initial_ready_count = initial_ready_count
        self.representation_builder = representation_builder or ProductRepresentationBuilder()
        self.similarity_engine = similarity_engine or SimilarityEngine()
        self.projection = projection or FixedProjection2D()
        self.focus_selector = focus_selector or FocusRingSelector()
        self.user_representation = self.representation_builder.for_brief(brief)
        self.profiles: dict[str, EnrichedProductProfile] = {}
        self.representations: dict[str, FeatureRepresentation] = {}
        self.user_similarities: dict[str, SimilarityResult] = {}
        self.product_similarities: dict[tuple[str, str], SimilarityResult] = {}
        self.nodes: dict[str, MapNode] = {}
        self.clusters: dict[str, MapCluster] = {}
        self.sequence = 0
        self.initial_ready = False
        self._user_emitted = False

    @property
    def user_node(self) -> MapNode:
        return MapNode(
            node_id=_stable_id("node", f"user:{self.brief.product_idea}"),
            candidate_id="user_idea",
            label=self.brief.product_idea,
            node_type="USER_IDEA",
            lifecycle="USER_IDEA",
            x=_CENTER[0],
            y=_CENTER[1],
            relationship="UNKNOWN",
            similarity_to_user=1.0,
        )

    def update(self, profiles: list[EnrichedProductProfile]) -> VisualizationDelta:
        incoming_ids = [profile.product_id for profile in profiles]
        if len(incoming_ids) != len(set(incoming_ids)):
            raise ValueError("profile updates must contain unique product_ids")

        old_cluster_ids = set(self.clusters)
        for profile in profiles:
            self.profiles[profile.product_id] = profile
            representation = self.representation_builder.for_product(profile)
            self.representations[profile.product_id] = representation
            self.user_similarities[profile.product_id] = self.similarity_engine.compare_to_user(
                representation,
                self.user_representation,
            )

        self._refresh_pairwise_similarities()
        upsert_nodes = []
        if not self._user_emitted:
            upsert_nodes.append(self.user_node)
            self._user_emitted = True

        occupied = [(node.x, node.y) for node in self.nodes.values()]
        occupied.append(_CENTER)
        for profile in sorted(profiles, key=lambda item: item.product_id):
            representation = self.representations[profile.product_id]
            similarity = self.user_similarities[profile.product_id]
            _, normalized_cluster, _ = _cluster_label(profile)
            cluster_id = _stable_id("cluster", normalized_cluster)
            existing = self.nodes.get(profile.product_id)
            if existing is None:
                x, y = self._position(profile.product_id, representation, similarity, occupied)
                occupied.append((x, y))
            else:
                x, y = existing.x, existing.y
            node = MapNode(
                node_id=_stable_id("node", profile.product_id),
                candidate_id=profile.candidate_id or profile.product_id,
                product_id=profile.product_id,
                label=profile.name,
                node_type="PRODUCT",
                lifecycle="ANALYZED",
                x=x,
                y=y,
                cluster_id=cluster_id,
                source_evidence_ids=profile.source_evidence_ids,
                relationship=semantic_relationship(profile),
                similarity_to_user=similarity.overall,
            )
            self.nodes[profile.product_id] = node
            upsert_nodes.append(node)

        self.clusters = self._build_clusters()
        removed_cluster_ids = sorted(old_cluster_ids - set(self.clusters))
        focus_ring = self.focus_selector.select(
            sorted(self.profiles.values(), key=lambda item: item.product_id),
            self.user_similarities,
        )

        product_count = len(self.nodes)
        if product_count >= self.initial_ready_count and not self.initial_ready:
            run_status = RunStatus.INITIAL_READY
            self.initial_ready = True
        else:
            run_status = RunStatus.ENRICHING
        degradation = (
            DegradationLevel.D2
            if product_count >= self.initial_ready_count
            else DegradationLevel.D3
        )
        delta = VisualizationDelta(
            sequence=self.sequence,
            run_status=run_status,
            degradation_level=degradation,
            upsert_nodes=upsert_nodes,
            upsert_clusters=sorted(
                self.clusters.values(),
                key=lambda cluster: cluster.cluster_id,
            ),
            remove_cluster_ids=removed_cluster_ids,
            focus_ring=focus_ring,
        )
        self.sequence += 1
        return delta

    def _refresh_pairwise_similarities(self) -> None:
        product_ids = sorted(self.representations)
        self.product_similarities = {}
        for index, left_id in enumerate(product_ids):
            for right_id in product_ids[index + 1 :]:
                result = self.similarity_engine.compare_products(
                    self.representations[left_id],
                    self.representations[right_id],
                )
                self.product_similarities[(left_id, right_id)] = result

    def _position(
        self,
        product_id: str,
        representation: FeatureRepresentation,
        similarity: SimilarityResult,
        occupied: list[tuple[float | None, float | None]],
    ) -> tuple[float, float]:
        radius = _MIN_RADIUS + (1 - similarity.overall) * (_MAX_RADIUS - _MIN_RADIUS)
        digest = hashlib.sha256(product_id.encode("utf-8")).digest()
        jitter = (int.from_bytes(digest[:2], "big") / 65535 - 0.5) * 0.12
        base_angle = self.projection.angle(representation) + jitter
        direction = 1 if digest[2] % 2 else -1

        for attempt in range(48):
            ring = attempt // 12
            step = (attempt + 1) // 2
            sign = direction if attempt % 2 else -direction
            angle = base_angle + sign * step * 0.11
            candidate_radius = min(_MAX_RADIUS, radius + ring * 0.12)
            x = round(_CENTER[0] + math.cos(angle) * candidate_radius, 4)
            y = round(_CENTER[1] + math.sin(angle) * candidate_radius, 4)
            if self._is_clear(x, y, occupied):
                return x, y
        fallback_angle = base_angle + math.pi / 3
        return (
            round(_CENTER[0] + math.cos(fallback_angle) * radius, 4),
            round(_CENTER[1] + math.sin(fallback_angle) * radius, 4),
        )

    @staticmethod
    def _is_clear(
        x: float,
        y: float,
        occupied: list[tuple[float | None, float | None]],
    ) -> bool:
        return all(
            other_x is None
            or other_y is None
            or math.dist((x, y), (other_x, other_y)) >= _MIN_NODE_DISTANCE
            for other_x, other_y in occupied
        )

    def _build_clusters(self) -> dict[str, MapCluster]:
        members: dict[str, list[str]] = {}
        labels: dict[str, list[tuple[str, str, str]]] = {}
        for product_id, profile in self.profiles.items():
            label, normalized, source = _cluster_label(profile)
            cluster_id = _stable_id("cluster", normalized)
            members.setdefault(cluster_id, []).append(product_id)
            labels.setdefault(cluster_id, []).append((label, normalized, source))

        clusters = {}
        for cluster_id, product_ids in members.items():
            product_ids.sort()
            points = [self.nodes[product_id] for product_id in product_ids]
            centroid_x = sum(node.x for node in points if node.x is not None) / len(points)
            centroid_y = sum(node.y for node in points if node.y is not None) / len(points)
            region_radius = max(
                math.dist((centroid_x, centroid_y), (node.x, node.y))
                for node in points
                if node.x is not None and node.y is not None
            )
            label, normalized, source = min(
                labels[cluster_id],
                key=lambda value: (value[0].casefold(), value[0]),
            )
            confidence = sum(self.profiles[product_id].confidence for product_id in product_ids)
            clusters[cluster_id] = MapCluster(
                cluster_id=cluster_id,
                name=label,
                description=f"Normalized market category: {label}.",
                product_ids=product_ids,
                confidence=round(confidence / len(product_ids), 3),
                normalized_label=normalized,
                label_source=source,
                centroid_x=round(centroid_x, 4),
                centroid_y=round(centroid_y, 4),
                region_radius=round(region_radius + 0.3, 4),
            )
        return clusters
