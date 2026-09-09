"""Evidence compression helpers for bounded analysis prompts and UI previews."""

from __future__ import annotations

from .contracts import CompactEvidenceItem, EvidenceItem


def _clip(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def compact_evidence_view(
    evidence: list[EvidenceItem],
    *,
    max_items: int = 6,
    text_limit: int = 420,
) -> list[CompactEvidenceItem]:
    return [
        CompactEvidenceItem(
            evidence_id=item.evidence_id,
            title=item.source.title or item.topic,
            url=item.source.url,
            claim=_clip(item.claim, 180),
            text=_clip(item.evidence_text, text_limit),
            confidence=item.confidence,
        )
        for item in evidence[:max_items]
    ]
