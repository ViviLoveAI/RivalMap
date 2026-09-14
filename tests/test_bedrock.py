from types import SimpleNamespace

import pytest

from rivalmap.bedrock import (
    BedrockConfigurationError,
    BedrockProviderError,
    BedrockSettings,
    create_bedrock_models,
)
from rivalmap.contracts import (
    CandidateRecord,
    EvidenceItem,
    EvidenceRelation,
    MarketBrief,
    ResearchBranch,
    ResearchEventType,
    SearchSeed,
    SemanticProductAnalysis,
    Source,
    SourceQuality,
    StructuredProductFacts,
)
from rivalmap.market_intelligence import MarketIntelligenceService, product_id_for_candidate
from rivalmap.research import ParallelResearchService
from rivalmap.strands_execution import (
    StrandsSemanticAnalyzer,
    StrandsStructuredAnalyzer,
    StructuredModelError,
    invoke_structured,
)


def _environment(**overrides):
    values = {
        "RIVALMAP_AWS_REGION": "us-west-2",
        "RIVALMAP_BEDROCK_MODEL_ID": "global.example.base-v1",
    }
    values.update(overrides)
    return values


def _candidate_and_evidence():
    evidence = EvidenceItem(
        evidence_id="ev-alpha",
        topic="Alpha",
        claim="Alpha is an interview coaching product.",
        source=Source(
            url="https://alpha.example",
            title="Alpha",
            quality=SourceQuality.PRIMARY,
        ),
        evidence_text="Alpha provides interview practice and feedback.",
        relation=EvidenceRelation.SUPPORTS,
        confidence=0.9,
    )
    candidate = CandidateRecord(
        candidate_id="candidate-alpha",
        name="Alpha",
        description=evidence.claim,
        source_evidence_ids=[evidence.evidence_id],
        canonical_url=evidence.source.url,
        domain="alpha.example",
    )
    return candidate, [evidence]


class FakeStructuredAgent:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.calls = []

    def __call__(self, prompt, *, structured_output_model):
        self.calls.append((prompt, structured_output_model))
        if self.error:
            raise self.error
        return SimpleNamespace(structured_output=self.output)


class FakeSearch:
    def __init__(self, responses):
        self.responses = responses

    def search(self, query, *, max_results, timeout_seconds):
        _ = max_results, timeout_seconds
        result = self.responses[query]
        if isinstance(result, Exception):
            raise result
        return result


def test_bedrock_configuration_requires_explicit_region_and_model_id():
    with pytest.raises(BedrockConfigurationError, match="RIVALMAP_AWS_REGION"):
        BedrockSettings.from_env({"RIVALMAP_BEDROCK_MODEL_ID": "model"})
    with pytest.raises(BedrockConfigurationError, match="RIVALMAP_BEDROCK_MODEL_ID"):
        BedrockSettings.from_env({"RIVALMAP_AWS_REGION": "us-west-2"})
    with pytest.raises(BedrockConfigurationError, match="valid AWS region"):
        BedrockSettings.from_env(_environment(RIVALMAP_AWS_REGION="not-a-region"))


def test_bedrock_role_models_are_configurable_with_different_depths():
    settings = BedrockSettings.from_env(
        _environment(
            RIVALMAP_BEDROCK_FRAMING_MODEL_ID="global.example.fast-v1",
            RIVALMAP_BEDROCK_INTELLIGENCE_MODEL_ID="global.example.deep-v1",
            RIVALMAP_BEDROCK_INTELLIGENCE_MAX_TOKENS="2048",
            RIVALMAP_BEDROCK_PRESENTATION_TEMPERATURE="0.3",
        )
    )

    assert settings.agents["framing"].model_id == "global.example.fast-v1"
    assert settings.agents["orchestrator"].model_id == "global.example.base-v1"
    assert settings.agents["intelligence"].model_id == "global.example.deep-v1"
    assert settings.agents["intelligence"].max_tokens == 2048
    assert settings.agents["presentation"].temperature == 0.3


def test_bedrock_factory_passes_region_and_never_supplies_credentials():
    calls = []

    def model_factory(**kwargs):
        calls.append(kwargs)
        return kwargs

    client_configs = []

    def client_config_factory(**kwargs):
        client_configs.append(kwargs)
        return "client-config"

    models = create_bedrock_models(
        BedrockSettings.from_env(_environment()),
        model_factory=model_factory,
        client_config_factory=client_config_factory,
    )

    assert len(calls) == 5
    assert {call["region_name"] for call in calls} == {"us-west-2"}
    assert all(call["boto_client_config"] == "client-config" for call in calls)
    assert not any("credential" in key or "access_key" in key for call in calls for key in call)
    assert models.framing["max_tokens"] < models.intelligence["max_tokens"]
    assert client_configs[0]["retries"] == {"max_attempts": 3, "mode": "standard"}


def test_bedrock_initialization_failure_is_normalized():
    def failing_factory(**kwargs):
        _ = kwargs
        raise OSError("provider unavailable")

    with pytest.raises(BedrockProviderError, match="Unable to initialize"):
        create_bedrock_models(
            BedrockSettings.from_env(_environment()),
            model_factory=failing_factory,
            client_config_factory=lambda **kwargs: kwargs,
        )


def test_malformed_structured_response_raises_safe_typed_error():
    agent = FakeStructuredAgent(output={"unexpected": "shape"})

    with pytest.raises(StructuredModelError, match="Invalid MarketBrief"):
        invoke_structured(agent, MarketBrief, "frame this")


def test_one_specialist_model_failure_falls_back_without_losing_evidence():
    candidate, evidence = _candidate_and_evidence()
    product_id = product_id_for_candidate(candidate.candidate_id)
    semantic = SemanticProductAnalysis(
        product_id=product_id,
        relationship="DIRECT",
        problem_solved="Interview practice",
        relevance_to_brief="Directly addresses interview preparation.",
        source_evidence_ids=["ev-alpha"],
        confidence=0.8,
    )
    structured_analyzer = StrandsStructuredAnalyzer(
        FakeStructuredAgent(error=RuntimeError("Bedrock unavailable"))
    )
    semantic_analyzer = StrandsSemanticAnalyzer(FakeStructuredAgent(output=semantic))

    structured_result = structured_analyzer.analyze(candidate, evidence)
    semantic_result = semantic_analyzer.analyze(candidate, evidence, MarketBrief(
        product_idea="AI interview coach",
        target_user="job seekers",
        problem="interview practice",
    ))

    assert structured_analyzer.last_error == "STRUCTURED_MODEL_FAILED"
    assert structured_result.source_evidence_ids == ["ev-alpha"]
    assert semantic_result.relationship == "DIRECT"
    assert semantic_analyzer.last_error is None


def test_malformed_structured_fact_output_uses_conservative_fallback():
    candidate, evidence = _candidate_and_evidence()
    analyzer = StrandsStructuredAnalyzer(
        FakeStructuredAgent(output={"unexpected": "shape"})
    )

    result = analyzer.analyze(candidate, evidence)

    assert analyzer.last_error == "STRUCTURED_MODEL_FAILED"
    assert result.product_id == product_id_for_candidate(candidate.candidate_id)
    assert result.source_evidence_ids == ["ev-alpha"]


def _research_with_partial_provider(responses):
    seeds = [
        SearchSeed(seed_id="direct", query="direct", branch=ResearchBranch.DIRECT),
        SearchSeed(seed_id="adjacent", query="adjacent", branch=ResearchBranch.ADJACENT),
    ]
    events = list(ParallelResearchService(FakeSearch(responses)).stream(
        MarketBrief(
            product_idea="AI interview coach",
            target_user="job seekers",
            problem="interview practice",
        ),
        seeds,
    ))
    assert events[-1].event == ResearchEventType.RESEARCH_WAVE_COMPLETE
    return events[-1].batch


def test_exa_success_is_preserved_when_intelligence_models_fail():
    candidate, evidence = _candidate_and_evidence()
    _ = candidate
    batch = _research_with_partial_provider({"direct": evidence, "adjacent": []})
    failing = FakeStructuredAgent(error=RuntimeError("Bedrock unavailable"))
    intelligence = MarketIntelligenceService(
        StrandsStructuredAnalyzer(failing),
        StrandsSemanticAnalyzer(failing),
    )

    events = list(intelligence.stream_batch(
        MarketBrief(
            product_idea="AI interview coach",
            target_user="job seekers",
            problem="interview practice",
        ),
        batch,
    ))

    profiles = [event.profile for event in events if event.profile is not None]
    assert len(profiles) == 1
    assert profiles[0].source_evidence_ids == ["ev-alpha"]


def test_model_success_is_preserved_when_one_exa_branch_fails():
    _, evidence = _candidate_and_evidence()
    batch = _research_with_partial_provider(
        {"direct": evidence, "adjacent": RuntimeError("Exa branch failed")}
    )
    product_id = product_id_for_candidate(batch.candidates[0].candidate_id)
    structured = StructuredProductFacts(
        product_id=product_id,
        product_name="Alpha",
        product_category="Interview coaching",
        source_evidence_ids=["ev-alpha"],
        confidence=0.9,
    )
    semantic = SemanticProductAnalysis(
        product_id=product_id,
        relationship="DIRECT",
        relevance_to_brief="Direct interview coaching competitor.",
        source_evidence_ids=["ev-alpha"],
        confidence=0.9,
    )
    intelligence = MarketIntelligenceService(
        StrandsStructuredAnalyzer(FakeStructuredAgent(output=structured)),
        StrandsSemanticAnalyzer(FakeStructuredAgent(output=semantic)),
    )

    events = list(intelligence.stream_batch(
        MarketBrief(
            product_idea="AI interview coach",
            target_user="job seekers",
            problem="interview practice",
        ),
        batch,
    ))

    profiles = [event.profile for event in events if event.profile is not None]
    assert len(profiles) == 1
    assert profiles[0].semantic_analysis.relationship == "DIRECT"
