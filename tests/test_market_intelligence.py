import threading
import time

from rivalmap.contracts import (
    AnalysisBudget,
    CandidateRecord,
    CandidateValidation,
    EvidenceItem,
    EvidenceRelation,
    IntelligenceEventType,
    MarketBrief,
    ResearchBatch,
    ResearchBranch,
    SearchSeed,
    SemanticProductAnalysis,
    Source,
    SourceQuality,
    StructuredProductFacts,
)
from rivalmap.market_intelligence import (
    CandidateIntelligenceInput,
    MarketIntelligenceService,
    ProductProfileFusion,
    product_id_for_candidate,
)


def _brief() -> MarketBrief:
    return MarketBrief(
        product_idea="AI interview coach",
        target_user="job seekers",
        problem="interview practice feedback",
    )


def _evidence(candidate_id: str) -> EvidenceItem:
    name = candidate_id.removeprefix("candidate-").title()
    return EvidenceItem(
        evidence_id=f"ev-{name.lower()}",
        topic=name,
        claim=f"{name} is an AI interview coaching product for job seekers.",
        source=Source(
            url=f"https://{name.lower()}.example",
            title=name,
            quality=SourceQuality.PRIMARY,
        ),
        evidence_text=f"{name} provides interview practice and feedback.",
        relation=EvidenceRelation.SUPPORTS,
        confidence=0.9,
    )


def _input(candidate_id: str, *, status="PASS") -> CandidateIntelligenceInput:
    evidence = _evidence(candidate_id)
    candidate = CandidateRecord(
        candidate_id=candidate_id,
        name=evidence.source.title,
        description=evidence.claim,
        source_evidence_ids=[evidence.evidence_id],
        canonical_url=evidence.source.url,
        domain=f"{evidence.source.title.lower()}.example",
    )
    validation = CandidateValidation(
        candidate_id=candidate_id,
        status=status,
        reason="Evidence-backed candidate.",
        source_evidence_ids=[evidence.evidence_id],
        is_product_or_company=True,
        relevance_score=0.8 if status == "PASS" else 0.15,
        identity_confidence=0.9,
        source_quality=SourceQuality.PRIMARY,
        evidence_coverage=1,
    )
    return CandidateIntelligenceInput(candidate, validation, (evidence,))


class _ConcurrencyTracker:
    def __init__(self):
        self.active = 0
        self.maximum = 0
        self._lock = threading.Lock()

    def enter(self):
        with self._lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)

    def leave(self):
        with self._lock:
            self.active -= 1


class MockStructuredAnalyzer:
    def __init__(self, *, delays=None, failures=None, evidence_override=None, tracker=None):
        self.delays = delays or {}
        self.failures = failures or set()
        self.evidence_override = evidence_override or {}
        self.tracker = tracker

    def analyze(self, candidate, evidence):
        if self.tracker:
            self.tracker.enter()
        try:
            time.sleep(self.delays.get(candidate.candidate_id, 0))
            if candidate.candidate_id in self.failures:
                raise RuntimeError("structured provider failed")
            evidence_ids = self.evidence_override.get(
                candidate.candidate_id,
                [item.evidence_id for item in evidence],
            )
            return StructuredProductFacts(
                product_id=product_id_for_candidate(candidate.candidate_id),
                product_name=candidate.name,
                company_name=candidate.name,
                canonical_url=candidate.canonical_url,
                positioning="Structured positioning",
                target_users=["job seekers"],
                product_category="Interview preparation",
                primary_use_case="Interview practice",
                features=["feedback"],
                workflow_coverage=["practice", "review"],
                pricing_signals=["subscription"],
                integrations=["calendar"],
                business_model="SaaS",
                source_evidence_ids=evidence_ids,
                field_evidence_ids={"features": evidence_ids},
                confidence=0.85,
            )
        finally:
            if self.tracker:
                self.tracker.leave()


class MockSemanticAnalyzer:
    def __init__(self, *, delays=None, failures=None, tracker=None):
        self.delays = delays or {}
        self.failures = failures or set()
        self.tracker = tracker

    def analyze(self, candidate, evidence, brief):
        if self.tracker:
            self.tracker.enter()
        try:
            time.sleep(self.delays.get(candidate.candidate_id, 0))
            if candidate.candidate_id in self.failures:
                raise RuntimeError("semantic provider failed")
            return SemanticProductAnalysis(
                product_id=product_id_for_candidate(candidate.candidate_id),
                directness="DIRECT",
                relationship="DIRECT",
                problem_solved="Interview preparation anxiety",
                core_workflow="Practice, receive feedback, and retry",
                positioning="Semantic positioning",
                relevance_to_brief=f"Directly addresses {brief.product_idea}.",
                differentiators=["Feedback depth"],
                uncertainties=["Pricing cadence is not confirmed."],
                source_evidence_ids=[item.evidence_id for item in evidence],
                confidence=0.8,
            )
        finally:
            if self.tracker:
                self.tracker.leave()


def _profiles(events):
    return [
        event.profile
        for event in events
        if event.event == IntelligenceEventType.PRODUCT_PROFILE_READY
    ]


def test_structured_and_semantic_paths_run_concurrently_and_emit_by_completion():
    tracker = _ConcurrencyTracker()
    item = _input("candidate-alpha")
    service = MarketIntelligenceService(
        MockStructuredAnalyzer(delays={"candidate-alpha": 0.02}, tracker=tracker),
        MockSemanticAnalyzer(delays={"candidate-alpha": 0.1}, tracker=tracker),
    )

    events = list(service.stream(_brief(), [item]))
    types = [event.event for event in events]

    assert tracker.maximum == 2
    assert types == [
        IntelligenceEventType.ANALYSIS_STARTED,
        IntelligenceEventType.STRUCTURED_ANALYSIS_COMPLETE,
        IntelligenceEventType.SEMANTIC_ANALYSIS_COMPLETE,
        IntelligenceEventType.PRODUCT_PROFILE_READY,
    ]
    assert _profiles(events)[0].analysis_status == "COMPLETE"


def test_one_path_failure_yields_partial_profile_without_losing_provenance():
    item = _input("candidate-alpha")
    service = MarketIntelligenceService(
        MockStructuredAnalyzer(failures={"candidate-alpha"}),
        MockSemanticAnalyzer(),
    )

    events = list(service.stream(_brief(), [item]))
    profile = _profiles(events)[0]

    assert any(
        event.event == IntelligenceEventType.ANALYSIS_PARTIAL
        and event.failed_path == "STRUCTURED"
        for event in events
    )
    assert profile.analysis_status == "PARTIAL"
    assert profile.semantic_analysis is not None
    assert profile.structured_facts.product_name == "Alpha"
    assert profile.field_origins["structured_facts"] == ["VALIDATION"]
    assert "Structured analysis path was unavailable." in profile.uncertainties
    assert profile.source_evidence_ids == ["ev-alpha"]
    assert profile.candidate_validation.source_evidence_ids == ["ev-alpha"]


def test_both_path_failures_emit_analysis_failed_without_profile():
    item = _input("candidate-alpha")
    service = MarketIntelligenceService(
        MockStructuredAnalyzer(failures={"candidate-alpha"}),
        MockSemanticAnalyzer(failures={"candidate-alpha"}),
    )

    events = list(service.stream(_brief(), [item]))

    assert _profiles(events) == []
    assert events[-1].event == IntelligenceEventType.ANALYSIS_FAILED
    assert events[-1].failed_path == "BOTH"


def test_multiple_candidates_run_concurrently_and_fast_profile_emits_first():
    tracker = _ConcurrencyTracker()
    structured = MockStructuredAnalyzer(
        delays={"candidate-fast": 0.01, "candidate-slow": 0.16},
        tracker=tracker,
    )
    semantic = MockSemanticAnalyzer(
        delays={"candidate-fast": 0.015, "candidate-slow": 0.17},
        tracker=tracker,
    )
    service = MarketIntelligenceService(
        structured,
        semantic,
        budget=AnalysisBudget(max_concurrent_candidates=2),
    )
    iterator = service.stream(
        _brief(),
        [_input("candidate-fast"), _input("candidate-slow")],
    )

    started = time.monotonic()
    observed = []
    while True:
        event = next(iterator)
        observed.append(event)
        if event.event == IntelligenceEventType.PRODUCT_PROFILE_READY:
            break
    first_profile_elapsed = time.monotonic() - started

    assert event.candidate_id == "candidate-fast"
    assert first_profile_elapsed < 0.12
    remaining = list(iterator)
    assert tracker.maximum >= 3
    assert [profile.candidate_id for profile in _profiles([*observed, *remaining])] == [
        "candidate-fast",
        "candidate-slow",
    ]


def test_fusion_is_deterministic_and_preserves_conflicting_path_claims():
    item = _input("candidate-alpha")
    structured = MockStructuredAnalyzer().analyze(item.candidate, list(item.evidence))
    semantic = MockSemanticAnalyzer().analyze(item.candidate, list(item.evidence), _brief())
    fusion = ProductProfileFusion()

    first = fusion.fuse(item, structured, semantic)
    second = fusion.fuse(item, structured, semantic)

    assert first == second
    assert first.structured_facts.positioning == "Structured positioning"
    assert first.semantic_analysis.positioning == "Semantic positioning"
    assert first.field_origins["positioning"] == ["STRUCTURED", "SEMANTIC"]
    assert "Structured and semantic positioning claims differ." in first.uncertainties
    assert first.source_evidence_ids == ["ev-alpha"]
    assert str(first.source_urls[0]) == "https://alpha.example/"


def test_unsupported_analysis_evidence_is_rejected_and_left_unknown():
    item = _input("candidate-alpha")
    service = MarketIntelligenceService(
        MockStructuredAnalyzer(evidence_override={"candidate-alpha": ["ev-unsupported"]}),
        MockSemanticAnalyzer(),
    )

    events = list(service.stream(_brief(), [item]))
    profile = _profiles(events)[0]

    assert any(
        event.event == IntelligenceEventType.ANALYSIS_PARTIAL
        and event.error_code == "INVALID_OUTPUT"
        for event in events
    )
    assert "ev-unsupported" not in profile.source_evidence_ids
    assert profile.structured_facts.business_model is None
    assert "business_model" in profile.structured_facts.missing_fields
    assert profile.analysis_status == "PARTIAL"


def test_only_selected_provisional_candidates_are_analyzed_from_batch():
    passed = _input("candidate-pass")
    provisional = _input("candidate-provisional", status="PROVISIONAL")
    seed = SearchSeed(query="interview products", branch=ResearchBranch.DIRECT)
    batch = ResearchBatch(
        seed=seed,
        evidence=[*passed.evidence, *provisional.evidence],
        candidates=[passed.candidate, provisional.candidate],
        validations=[passed.validation, provisional.validation],
    )
    service = MarketIntelligenceService(
        MockStructuredAnalyzer(),
        MockSemanticAnalyzer(),
    )

    default_events = list(service.stream_batch(_brief(), batch))
    selected_events = list(
        service.stream_batch(
            _brief(),
            batch,
            selected_provisional_ids={"candidate-provisional"},
        )
    )

    assert [profile.candidate_id for profile in _profiles(default_events)] == [
        "candidate-pass"
    ]
    assert {profile.candidate_id for profile in _profiles(selected_events)} == {
        "candidate-pass",
        "candidate-provisional",
    }


def test_existing_model_router_boundary_can_drive_both_analysis_paths():
    item = _input("candidate-alpha")

    class MockRouter:
        def __init__(self):
            self.tasks = []

        def generate(self, schema, *, system, payload, task):
            self.tasks.append(task)
            assert "evidence" in payload
            assert "chain-of-thought" not in system.casefold()
            if schema is StructuredProductFacts:
                return StructuredProductFacts(
                    product_id=product_id_for_candidate("candidate-alpha"),
                    product_name="Alpha",
                    primary_use_case="Interview practice",
                    source_evidence_ids=["ev-alpha"],
                    confidence=0.8,
                )
            return SemanticProductAnalysis(
                product_id=product_id_for_candidate("candidate-alpha"),
                relationship="DIRECT",
                relevance_to_brief="Direct interview-practice workflow.",
                source_evidence_ids=["ev-alpha"],
                confidence=0.8,
            )

    router = MockRouter()
    events = list(MarketIntelligenceService.from_router(router).stream(_brief(), [item]))

    assert _profiles(events)[0].analysis_status == "COMPLETE"
    assert set(router.tasks) == {
        "rivalmap_structured_product_analysis",
        "rivalmap_semantic_product_analysis",
    }
