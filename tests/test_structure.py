from rivalmap.contracts import EvidenceItem, EvidenceRelation, Source, SourceQuality
from rivalmap.structure import build_market_structure, product_map_from_structure


def _evidence(index: int, title: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"ev-{index}",
        topic=title,
        claim=f"{title} is an AI mock interview practice tool with feedback.",
        source=Source(url=f"https://example.com/{index}", title=title, quality=SourceQuality.PRIMARY),
        evidence_text="AI speaking practice, mock interview, score feedback.",
        relation=EvidenceRelation.CONTEXT,
        confidence=0.8,
    )


def test_structure_and_base_map_are_deterministic_survival_path():
    structure = build_market_structure([_evidence(1, "Speak"), _evidence(2, "Loora")])
    base_map = product_map_from_structure(structure)

    assert len(structure.products) == 2
    assert structure.degradation_level == "D2"
    assert base_map is not None
    assert len(base_map.points) == 2
