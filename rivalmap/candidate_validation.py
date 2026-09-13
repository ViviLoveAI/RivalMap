"""Lightweight candidate validation kept separate from research control."""

from __future__ import annotations

import re
from typing import Protocol

from .contracts import (
    CandidateRecord,
    CandidateValidation,
    EvidenceItem,
    MarketBrief,
    SourceQuality,
)

_PRODUCT_MARKERS = (
    "app",
    "assistant",
    "coach",
    "company",
    "platform",
    "product",
    "service",
    "software",
    "solution",
    "tool",
    "workflow",
    "应用",
    "产品",
    "公司",
    "平台",
    "工具",
    "服务",
)
_CONTENT_MARKERS = (
    "article",
    "blog",
    "guide",
    "journal",
    "news",
    "paper",
    "report",
    "research",
    "top 10",
    "论文",
    "报告",
    "新闻",
    "研究",
)
_GENERIC_NAMES = {"article", "blog", "guide", "home", "news", "report", "research"}
_STOP_WORDS = {
    "about",
    "and",
    "for",
    "from",
    "into",
    "the",
    "this",
    "tool",
    "with",
    "your",
}
_QUALITY_SCORE = {
    SourceQuality.PRIMARY: 1.0,
    SourceQuality.SECONDARY: 0.75,
    SourceQuality.UNKNOWN: 0.55,
    SourceQuality.AGGREGATOR: 0.35,
}


class SemanticCandidateValidator(Protocol):
    """Optional future semantic check; implementations must remain provider-agnostic."""

    def validate(
        self,
        candidate: CandidateRecord,
        evidence: list[EvidenceItem],
        brief: MarketBrief,
    ) -> CandidateValidation:
        """Return a schema-validated decision without controlling research sufficiency."""


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w-]{3,}", text.casefold(), flags=re.UNICODE)
        if token not in _STOP_WORDS
    }


class RuleBasedCandidateValidator:
    """Fast deterministic gate for candidate admission."""

    def validate(
        self,
        candidate: CandidateRecord,
        evidence: list[EvidenceItem],
        brief: MarketBrief,
    ) -> CandidateValidation:
        candidate_evidence = sorted(
            (
                item
                for item in evidence
                if item.evidence_id in candidate.source_evidence_ids
            ),
            key=lambda item: item.evidence_id,
        )
        evidence_text = " ".join(
            f"{item.source.title} {item.claim} {item.evidence_text}"
            for item in candidate_evidence
        ).casefold()
        has_product_marker = any(marker in evidence_text for marker in _PRODUCT_MARKERS)
        content_markers = sum(marker in evidence_text for marker in _CONTENT_MARKERS)
        is_product = has_product_marker and content_markers < 2

        brief_text = " ".join(
            part
            for part in (brief.product_idea, brief.target_user, brief.problem)
            if part
        )
        brief_tokens = _tokens(brief_text)
        candidate_tokens = _tokens(f"{candidate.name} {candidate.description} {evidence_text}")
        overlap = len(brief_tokens.intersection(candidate_tokens))
        relevance = min(1.0, overlap / max(1, min(len(brief_tokens), 5)))

        generic_name = candidate.name.casefold() in _GENERIC_NAMES or len(candidate.name) < 2
        identity_confidence = 0.9 if candidate.domain and not generic_name else 0.45
        qualities = [item.source.quality for item in candidate_evidence]
        source_quality = max(qualities, key=_QUALITY_SCORE.get) if qualities else SourceQuality.UNKNOWN
        coverage = len({item.evidence_id for item in candidate_evidence})

        if not is_product:
            status = "REJECT"
            reason = "Source does not describe a recognizable product or company."
        elif identity_confidence < 0.6 or relevance < 0.1:
            status = "REJECT"
            reason = "Candidate identity or relevance is too weak."
        elif (
            relevance >= 0.2
            and identity_confidence >= 0.7
            and source_quality != SourceQuality.AGGREGATOR
            and coverage >= 1
        ):
            status = "PASS"
            reason = "Product identity and brief relevance are supported by evidence."
        else:
            status = "PROVISIONAL"
            reason = "Candidate is plausible but needs stronger source or relevance evidence."

        return CandidateValidation(
            candidate_id=candidate.candidate_id,
            status=status,
            reason=reason,
            source_evidence_ids=[item.evidence_id for item in candidate_evidence],
            is_product_or_company=is_product,
            relevance_score=round(relevance, 3),
            identity_confidence=identity_confidence,
            source_quality=source_quality,
            evidence_coverage=coverage,
        )
