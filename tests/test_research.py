import json
import threading
import time
from unittest.mock import patch

from rivalmap.adapters.exa import ExaDiscoveryService
from rivalmap.candidate_normalization import candidate_from_evidence
from rivalmap.candidate_validation import RuleBasedCandidateValidator
from rivalmap.contracts import (
    EvidenceItem,
    EvidenceRelation,
    MarketBrief,
    ResearchBranch,
    ResearchBudget,
    ResearchEventType,
    SearchSeed,
    Source,
    SourceQuality,
)
from rivalmap.research import DeterministicResearchPlanner, ParallelResearchService


def _evidence(
    evidence_id: str,
    title: str,
    url: str,
    text: str,
    *,
    quality: SourceQuality = SourceQuality.PRIMARY,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        topic=title,
        claim=text,
        source=Source(url=url, title=title, quality=quality),
        evidence_text=text,
        relation=EvidenceRelation.CONTEXT,
        confidence=0.85,
    )


def _seeds() -> list[SearchSeed]:
    return [
        SearchSeed(seed_id="seed-direct", query="direct", branch=ResearchBranch.DIRECT),
        SearchSeed(seed_id="seed-adjacent", query="adjacent", branch=ResearchBranch.ADJACENT),
    ]


class FakeSearch:
    def __init__(self, responses, delays=None):
        self.responses = responses
        self.delays = delays or {}
        self.active = 0
        self.max_active = 0
        self.calls = []
        self._lock = threading.Lock()

    def search(self, query, *, max_results, timeout_seconds):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append((query, max_results, timeout_seconds))
        try:
            time.sleep(self.delays.get(query, 0))
            response = self.responses[query]
            if isinstance(response, Exception):
                raise response
            return response
        finally:
            with self._lock:
                self.active -= 1


def _service(
    search,
    *,
    request_timeout=0.5,
    wave_timeout=1.0,
    max_queries=4,
    max_candidates=6,
):
    return ParallelResearchService(
        search,
        budget=ResearchBudget(
            max_concurrent_searches=4,
            max_queries_per_wave=max_queries,
            max_candidates_per_query=max_candidates,
            request_timeout_seconds=request_timeout,
            wave_timeout_seconds=wave_timeout,
        ),
    )


def _brief() -> MarketBrief:
    return MarketBrief(
        product_idea="AI interview coach",
        target_user="job seekers",
        problem="interview practice feedback",
    )


def _final(events):
    assert events[-1].event == ResearchEventType.RESEARCH_WAVE_COMPLETE
    return events[-1]


def test_research_queries_execute_concurrently_and_cover_deterministic_branches():
    alpha = _evidence(
        "ev-alpha",
        "Alpha Interview Coach",
        "https://alpha.example/product",
        "Alpha is an AI interview coach product for job seekers.",
    )
    beta = _evidence(
        "ev-beta",
        "Beta Practice Platform",
        "https://beta.example",
        "Beta is an interview practice platform with feedback.",
    )
    search = FakeSearch(
        {"direct": [alpha], "adjacent": [beta]},
        delays={"direct": 0.04, "adjacent": 0.04},
    )

    events = list(_service(search).stream(_brief(), _seeds()))
    final = _final(events)

    assert search.max_active == 2
    assert final.summary.queries_completed == 2
    assert final.summary.queries_failed == 0
    assert final.summary.search_branches_covered == [
        ResearchBranch.DIRECT,
        ResearchBranch.ADJACENT,
    ]
    assert {call[0] for call in search.calls} == {"direct", "adjacent"}


def test_fast_candidate_is_emitted_before_slow_branch_completes():
    alpha = _evidence(
        "ev-alpha",
        "Alpha Interview Coach",
        "https://alpha.example",
        "Alpha is an AI interview coach product for job seekers.",
    )
    beta = _evidence(
        "ev-beta",
        "Beta Interview Platform",
        "https://beta.example",
        "Beta is an interview platform for job seekers.",
    )
    search = FakeSearch(
        {"direct": [alpha], "adjacent": [beta]},
        delays={"direct": 0.01, "adjacent": 0.18},
    )
    iterator = _service(search).stream(_brief(), _seeds())

    started = time.monotonic()
    first = next(iterator)
    first_elapsed = time.monotonic() - started

    assert first.event == ResearchEventType.CANDIDATE_FOUND
    assert first.candidate.name == "Alpha Interview Coach"
    assert first_elapsed < 0.12
    remaining = list(iterator)
    assert _final([first, *remaining]).summary.queries_completed == 2


def test_partial_failure_and_malformed_results_preserve_successful_candidates():
    alpha = _evidence(
        "ev-alpha",
        "Alpha Interview Coach",
        "https://alpha.example",
        "Alpha is an AI interview coach product with interview feedback.",
    )
    search = FakeSearch(
        {
            "direct": [None, {"bad": "shape"}, alpha],
            "adjacent": RuntimeError("provider unavailable"),
        }
    )

    events = list(_service(search).stream(_brief(), _seeds()))
    final = _final(events)

    assert final.summary.queries_completed == 1
    assert final.summary.queries_failed == 1
    assert final.summary.passed == 1
    assert [candidate.name for candidate in final.batch.candidates] == [
        "Alpha Interview Coach"
    ]
    assert any(event.error_code == "SEARCH_FAILED" for event in events)


def test_one_query_timeout_does_not_delay_or_erase_completed_branch():
    alpha = _evidence(
        "ev-alpha",
        "Alpha Interview Coach",
        "https://alpha.example",
        "Alpha is an AI interview coach product with interview feedback.",
    )
    beta = _evidence(
        "ev-beta",
        "Beta Interview Coach",
        "https://beta.example",
        "Beta is an interview coach product.",
    )
    search = FakeSearch(
        {"direct": [alpha], "adjacent": [beta]},
        delays={"direct": 0.005, "adjacent": 0.2},
    )

    started = time.monotonic()
    events = list(
        _service(search, request_timeout=0.04, wave_timeout=0.3).stream(
            _brief(), _seeds()
        )
    )
    elapsed = time.monotonic() - started
    final = _final(events)

    assert elapsed < 0.15
    assert final.summary.queries_completed == 1
    assert final.summary.queries_failed == 1
    assert final.summary.passed == 1
    assert final.batch.candidates[0].source_evidence_ids == ["ev-alpha"]
    assert any(event.error_code == "TIMEOUT" for event in events)


def test_deduplication_stable_ids_and_provenance_are_deterministic():
    first = _evidence(
        "ev-alpha-1",
        "Alpha - AI Interview Coach",
        "https://www.alpha.example/product?ref=search",
        "Alpha is an AI interview coach product for job seekers.",
    )
    second = _evidence(
        "ev-alpha-2",
        "Alpha | Official Site",
        "https://alpha.example/",
        "Alpha is an interview practice platform with feedback.",
    )
    expected_id = candidate_from_evidence(first).candidate_id

    def run_once():
        search = FakeSearch({"direct": [first], "adjacent": [second]})
        return _final(list(_service(search).stream(_brief(), _seeds())))

    first_run = run_once()
    second_run = run_once()

    assert first_run.batch.batch_id == second_run.batch.batch_id
    assert len(first_run.batch.candidates) == 1
    candidate = first_run.batch.candidates[0]
    assert candidate.candidate_id == expected_id
    assert candidate.domain == "alpha.example"
    assert str(candidate.canonical_url) == "https://alpha.example/"
    assert candidate.source_evidence_ids == ["ev-alpha-1", "ev-alpha-2"]
    assert first_run.batch.validations[0].status == "PASS"
    assert {item.evidence_id for item in first_run.batch.evidence} == {
        "ev-alpha-1",
        "ev-alpha-2",
    }
    assert first_run.summary == second_run.summary


def test_validation_gate_emits_pass_provisional_and_reject():
    validator = RuleBasedCandidateValidator()
    brief = _brief()
    cases = [
        (
            _evidence(
                "ev-pass",
                "Alpha Interview Coach",
                "https://alpha.example",
                "Alpha is an AI interview coach product for job seekers.",
            ),
            "PASS",
        ),
        (
            _evidence(
                "ev-provisional",
                "Beta Interview Platform",
                "https://directory.example/beta",
                "Beta is an interview practice software platform.",
                quality=SourceQuality.AGGREGATOR,
            ),
            "PROVISIONAL",
        ),
        (
            _evidence(
                "ev-reject",
                "Interview Market Research Report",
                "https://news.example/report",
                "A research report and news article about interview trends.",
            ),
            "REJECT",
        ),
    ]

    decisions = []
    for evidence, expected in cases:
        candidate = candidate_from_evidence(evidence)
        validation = validator.validate(candidate, [evidence], brief)
        decisions.append(validation.status)
        assert validation.status == expected
        assert validation.source_evidence_ids == [evidence.evidence_id]

    assert decisions == ["PASS", "PROVISIONAL", "REJECT"]


def test_rejected_candidates_are_emitted_but_do_not_enter_research_batch():
    accepted = _evidence(
        "ev-pass",
        "Alpha Interview Coach",
        "https://alpha.example",
        "Alpha is an AI interview coach product for job seekers.",
    )
    rejected = _evidence(
        "ev-reject",
        "Interview Market Research Report",
        "https://news.example/report",
        "A research report and news article about interview trends.",
    )
    search = FakeSearch({"direct": [accepted, rejected]})

    events = list(_service(search).stream(_brief(), [_seeds()[0]]))
    final = _final(events)

    assert final.summary.candidates_found == 2
    assert final.summary.passed == 1
    assert final.summary.rejected == 1
    assert [candidate.name for candidate in final.batch.candidates] == [
        "Alpha Interview Coach"
    ]
    assert [validation.status for validation in final.batch.validations] == ["PASS"]
    assert any(
        event.validation and event.validation.status == "REJECT" for event in events
    )


def test_planner_and_query_budget_are_deterministic():
    planner = DeterministicResearchPlanner()
    first = planner.plan(_brief())
    second = planner.plan(_brief())

    assert first == second
    assert [seed.branch for seed in first] == [
        ResearchBranch.DIRECT,
        ResearchBranch.ADJACENT,
        ResearchBranch.CATEGORY,
        ResearchBranch.ALTERNATIVES,
    ]
    search = FakeSearch({seed.query: [] for seed in first})
    final = _final(list(_service(search, max_queries=2).stream(_brief())))
    assert len(search.calls) == 2
    assert final.summary.queries_completed == 2


def test_candidate_and_wave_budgets_are_enforced():
    evidence = [
        _evidence(
            f"ev-{index}",
            f"Product {index} Interview Coach",
            f"https://product-{index}.example",
            f"Product {index} is an interview coach platform.",
        )
        for index in range(3)
    ]
    search = FakeSearch({"direct": evidence})
    final = _final(
        list(
            _service(search, max_candidates=1).stream(
                _brief(),
                [_seeds()[0]],
            )
        )
    )

    assert search.calls == [("direct", 1, 0.5)]
    assert final.summary.candidates_found == 1
    assert len(final.batch.candidates) == 1

    slow = FakeSearch(
        {"direct": evidence, "adjacent": evidence},
        delays={"direct": 0.2, "adjacent": 0.2},
    )
    started = time.monotonic()
    timed_out = _final(
        list(
            _service(slow, request_timeout=0.5, wave_timeout=0.03).stream(
                _brief(), _seeds()
            )
        )
    )
    assert time.monotonic() - started < 0.15
    assert timed_out.summary.queries_completed == 0
    assert timed_out.summary.queries_failed == 2
    assert timed_out.summary.research_continuing is False


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_exa_adapter_exposes_independently_budgeted_search_call():
    payload = {
        "results": [
            {
                "url": "https://alpha.example",
                "title": "Alpha Interview Coach",
                "highlights": ["Alpha is an interview coach product."],
                "score": 0.82,
            },
            {"title": "Malformed without URL"},
        ]
    }
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Response(payload)

    adapter = ExaDiscoveryService(api_key="test-key")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        evidence = adapter.search("direct competitors", max_results=3, timeout_seconds=1.25)

    assert captured == {
        "body": {
            "query": "direct competitors",
            "type": "fast",
            "numResults": 3,
            "contents": {"highlights": True},
        },
        "timeout": 1.25,
    }
    assert len(evidence) == 1
    assert str(evidence[0].source.url) == "https://alpha.example/"
