"""Explainable deterministic representations, similarity, and Focus Ring ranking."""

from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    EnrichedProductProfile,
    FocusRingEntry,
    MarketBrief,
    SimilarityResult,
    SourceQuality,
)

_DIMENSION_WEIGHTS = {
    "target_customer": 0.15,
    "problem": 0.20,
    "workflow": 0.20,
    "category": 0.15,
    "capabilities": 0.15,
    "positioning": 0.10,
    "differentiators": 0.05,
}
_RELATIONSHIP_PRIOR = {
    "DIRECT": 1.0,
    "ADJACENT": 0.65,
    "ALTERNATIVE": 0.4,
    "UNKNOWN": 0.25,
}
_SOURCE_QUALITY = {
    SourceQuality.PRIMARY: 1.0,
    SourceQuality.SECONDARY: 0.8,
    SourceQuality.UNKNOWN: 0.55,
    SourceQuality.AGGREGATOR: 0.35,
}
_STOP_WORDS = {
    "about",
    "and",
    "for",
    "from",
    "into",
    "product",
    "service",
    "that",
    "the",
    "this",
    "tool",
    "with",
    "your",
}
_STRUCTURED_FIELD_COUNT = 10
_PROJECTION_DIMENSIONS = 256
_PROJECTION_SEED = 0x524956414C4D4150


class EmbeddingProvider(Protocol):
    """Optional provider-neutral extension; deterministic features remain authoritative."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per text without controlling map coordinates."""


@dataclass(frozen=True)
class FeatureRepresentation:
    entity_id: str
    dimensions: dict[str, frozenset[str]]
    relationship: str = "UNKNOWN"


def _tokens(values: list[str]) -> frozenset[str]:
    normalized: set[str] = set()
    for value in values:
        for token in re.findall(r"[\w-]{2,}", value.casefold(), flags=re.UNICODE):
            if token in _STOP_WORDS:
                continue
            if token.endswith("s") and len(token) > 4:
                token = token[:-1]
            normalized.add(token)
    return frozenset(normalized)


def _strings(*values: str | None) -> list[str]:
    return [value for value in values if value]


def semantic_relationship(profile: EnrichedProductProfile) -> str:
    """Return the STEP 3 semantic relationship; never consult legacy directness."""

    if profile.semantic_analysis is None:
        return "UNKNOWN"
    return profile.semantic_analysis.relationship


class ProductRepresentationBuilder:
    def for_brief(self, brief: MarketBrief) -> FeatureRepresentation:
        idea = brief.product_idea
        problem = brief.problem
        return FeatureRepresentation(
            entity_id="user_idea",
            dimensions={
                "target_customer": _tokens(_strings(brief.target_user)),
                "problem": _tokens(_strings(problem, idea)),
                "workflow": _tokens(_strings(problem, idea)),
                "category": _tokens([idea]),
                "capabilities": _tokens(_strings(problem, idea)),
                "positioning": _tokens([idea]),
                "differentiators": frozenset(),
            },
        )

    def for_product(self, profile: EnrichedProductProfile) -> FeatureRepresentation:
        facts = profile.structured_facts
        semantic = profile.semantic_analysis
        return FeatureRepresentation(
            entity_id=profile.product_id,
            dimensions={
                "target_customer": _tokens(facts.target_users),
                "problem": _tokens(
                    _strings(
                        semantic.problem_solved if semantic else None,
                        facts.primary_use_case,
                    )
                ),
                "workflow": _tokens(
                    [
                        *facts.workflow_coverage,
                        *_strings(semantic.core_workflow if semantic else None),
                    ]
                ),
                "category": _tokens(_strings(facts.product_category)),
                "capabilities": _tokens(facts.features),
                "positioning": _tokens(
                    _strings(
                        facts.positioning,
                        semantic.positioning if semantic else None,
                    )
                ),
                "differentiators": _tokens(
                    semantic.differentiators if semantic else []
                ),
            },
            relationship=semantic_relationship(profile),
        )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left.union(right))


class SimilarityEngine:
    def compare_to_user(
        self,
        product: FeatureRepresentation,
        user: FeatureRepresentation,
    ) -> SimilarityResult:
        dimensions = {
            name: _jaccard(product.dimensions[name], user.dimensions[name])
            for name in _DIMENSION_WEIGHTS
        }
        content_score = sum(
            dimensions[name] * weight for name, weight in _DIMENSION_WEIGHTS.items()
        )
        return SimilarityResult(
            overall=round(min(max(content_score, 0), 1), 6),
            dimension_scores={name: round(score, 6) for name, score in dimensions.items()},
            relationship=product.relationship,
        )

    def compare_products(
        self,
        left: FeatureRepresentation,
        right: FeatureRepresentation,
    ) -> SimilarityResult:
        dimensions = {
            name: _jaccard(left.dimensions[name], right.dimensions[name])
            for name in _DIMENSION_WEIGHTS
        }
        overall = sum(
            dimensions[name] * weight for name, weight in _DIMENSION_WEIGHTS.items()
        )
        return SimilarityResult(
            overall=round(min(max(overall, 0), 1), 6),
            dimension_scores={name: round(score, 6) for name, score in dimensions.items()},
        )


class FixedProjection2D:
    """Fixed-seed projection that supports deterministic out-of-sample placement."""

    def __init__(
        self,
        *,
        dimensions: int = _PROJECTION_DIMENSIONS,
        seed: int = _PROJECTION_SEED,
    ) -> None:
        if dimensions < 2:
            raise ValueError("projection dimensions must be at least two")
        self.dimensions = dimensions
        generator = random.Random(seed)
        self._matrix = tuple(
            (generator.gauss(0, 1), generator.gauss(0, 1))
            for _ in range(dimensions)
        )

    def feature_vector(self, representation: FeatureRepresentation) -> tuple[float, ...]:
        """Encode normalized market features independently of identity and relationship."""

        vector = [0.0] * self.dimensions
        for dimension, weight in _DIMENSION_WEIGHTS.items():
            tokens = representation.dimensions[dimension]
            if not tokens:
                continue
            token_weight = weight / math.sqrt(len(tokens))
            for token in tokens:
                digest = hashlib.sha256(f"{dimension}:{token}".encode()).digest()
                bucket = int.from_bytes(digest[:8], "big") % self.dimensions
                sign = 1.0 if digest[8] & 1 else -1.0
                vector[bucket] += sign * token_weight
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return tuple(vector)
        return tuple(value / norm for value in vector)

    def project(self, representation: FeatureRepresentation) -> tuple[float, float]:
        vector = self.feature_vector(representation)
        x = sum(value * self._matrix[index][0] for index, value in enumerate(vector))
        y = sum(value * self._matrix[index][1] for index, value in enumerate(vector))
        norm = math.hypot(x, y)
        if norm < 1e-12:
            return (1.0, 0.0)
        return (x / norm, y / norm)

    def angle(self, representation: FeatureRepresentation) -> float:
        x, y = self.project(representation)
        return math.atan2(y, x)


class FocusRingSelector:
    def __init__(self, *, maximum_size: int = 6, minimum_similarity: float = 0.15):
        self.maximum_size = maximum_size
        self.minimum_similarity = minimum_similarity

    def select(
        self,
        profiles: list[EnrichedProductProfile],
        similarities: dict[str, SimilarityResult],
    ) -> list[FocusRingEntry]:
        scored: list[tuple[float, str, list[str]]] = []
        for profile in profiles:
            similarity = similarities[profile.product_id].overall
            validation = profile.candidate_validation
            if validation is None or validation.evidence_coverage < 1:
                continue
            if similarity < self.minimum_similarity or profile.confidence < 0.35:
                continue

            relationship = semantic_relationship(profile)
            relationship_score = _RELATIONSHIP_PRIOR[relationship]
            coverage_score = min(validation.evidence_coverage / 3, 1.0)
            evidence_score = (
                0.65 * coverage_score + 0.35 * _SOURCE_QUALITY[validation.source_quality]
            )
            completeness = max(
                0.0,
                1 - len(set(profile.structured_facts.missing_fields)) / _STRUCTURED_FIELD_COUNT,
            )
            profile_quality = 0.55 * completeness + 0.45 * profile.confidence
            if profile.analysis_status == "PARTIAL":
                profile_quality *= 0.75
            proximity = (
                0.50 * similarity
                + 0.20 * relationship_score
                + 0.15 * evidence_score
                + 0.15 * profile_quality
            )

            reasons = []
            if similarity >= 0.5:
                reasons.append("HIGH_USER_SIMILARITY")
            if relationship != "UNKNOWN":
                reasons.append(f"{relationship}_RELATIONSHIP")
            if evidence_score >= 0.65:
                reasons.append("STRONG_EVIDENCE")
            else:
                reasons.append("EVIDENCE_LIMITED")
            if profile_quality >= 0.7:
                reasons.append("HIGH_PROFILE_QUALITY")
            scored.append((round(proximity, 6), profile.product_id, reasons))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            FocusRingEntry(
                product_id=product_id,
                rank=rank,
                proximity_score=score,
                reasons=reasons,
            )
            for rank, (score, product_id, reasons) in enumerate(
                scored[: self.maximum_size],
                start=1,
            )
        ]
