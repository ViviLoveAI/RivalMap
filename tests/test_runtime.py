from rivalmap.contracts import (
    EvidenceItem,
    EvidenceRelation,
    RivalMapRequest,
    Source,
    SourceQuality,
)
from rivalmap.runtime import RivalMapRuntime


class FakeDiscovery:
    def discover(self, request):
        return [
            EvidenceItem(
                evidence_id="ev-speak",
                topic="Speak",
                claim="Speak is an AI speaking practice app with feedback.",
                source=Source(url="https://example.com/speak", title="Speak", quality=SourceQuality.PRIMARY),
                evidence_text="AI speaking practice app, feedback, language expression.",
                relation=EvidenceRelation.CONTEXT,
                confidence=0.8,
            ),
            EvidenceItem(
                evidence_id="ev-loora",
                topic="Loora",
                claim="Loora is an AI English conversation coach.",
                source=Source(url="https://example.com/loora", title="Loora", quality=SourceQuality.PRIMARY),
                evidence_text="AI English conversation coach, speaking feedback.",
                relation=EvidenceRelation.CONTEXT,
                confidence=0.78,
            ),
        ]


def test_runtime_returns_stable_rival_map_state_without_live_exa():
    runtime = RivalMapRuntime(discovery=FakeDiscovery())
    result = runtime.run(RivalMapRequest(idea="帮助留学生练习英语面试的工具", target_user="留学生"))

    assert result.session.product_idea == "帮助留学生练习英语面试的工具"
    assert result.market_structure is not None
    assert result.base_map is not None
    assert result.interpretive_analysis is not None
    assert result.degradation_level == "D1"
    assert "base_map" in result.capabilities


def test_stream_exposes_typed_progress_events():
    runtime = RivalMapRuntime(discovery=FakeDiscovery())
    events = list(runtime.stream(RivalMapRequest(idea="AI interview practice")))

    assert [event.event.value for event in events] == [
        "run_started",
        "discovery_started",
        "evidence_ready",
        "structure_ready",
        "base_map_ready",
        "analysis_ready",
        "rival_map_ready",
    ]
