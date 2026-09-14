from fastapi import FastAPI
from fastapi.testclient import TestClient

from rivalmap.api import create_router
from rivalmap.contracts import (
    AgentEvent,
    AgentEventType,
    EvidenceItem,
    EvidenceRelation,
    MarketBrief,
    RunStatus,
    Source,
    SourceQuality,
)
from rivalmap.refinement import ActiveRunRegistry
from rivalmap.runtime import RivalMapRuntime


class FakeDiscovery:
    def discover(self, request):
        return [
            EvidenceItem(
                evidence_id="ev-a",
                topic="A",
                claim="A is an AI interview practice tool with feedback.",
                source=Source(url="https://example.com/a", title="A", quality=SourceQuality.PRIMARY),
                evidence_text="AI interview practice feedback.",
                relation=EvidenceRelation.CONTEXT,
                confidence=0.8,
            ),
            EvidenceItem(
                evidence_id="ev-b",
                topic="B",
                claim="B is an AI mock interview assistant.",
                source=Source(url="https://example.com/b", title="B", quality=SourceQuality.PRIMARY),
                evidence_text="Mock interview assistant with speaking feedback.",
                relation=EvidenceRelation.CONTEXT,
                confidence=0.78,
            ),
        ]


def _client():
    app = FastAPI()
    app.include_router(create_router(RivalMapRuntime(discovery=FakeDiscovery())))
    return TestClient(app)


def test_run_endpoint_returns_rival_map_state():
    response = _client().post("/api/runs", json={"idea": "AI interview practice"})

    assert response.status_code == 200
    data = response.json()
    assert data["base_map"]["points"]
    assert data["degradation_level"] == "D1"


def test_stream_endpoint_returns_progress_events():
    response = _client().post("/api/runs/stream", json={"idea": "AI interview practice"})

    assert response.status_code == 200
    assert "event: evidence_ready" in response.text
    assert "event: rival_map_ready" in response.text


class FakeProgressiveRunner:
    def stream(self, product_idea, *, target_user, problem):
        _ = target_user, problem
        yield AgentEvent(
            event=AgentEventType.FRAMING_STARTED,
            run_status=RunStatus.FRAMING,
            message=f"Framing {product_idea}.",
        )
        yield AgentEvent(
            event=AgentEventType.ORCHESTRATION_COMPLETE,
            run_status=RunStatus.COMPLETE,
            message="RivalMap orchestration complete.",
        )


def test_progressive_stream_exposes_safe_agent_events_without_eager_provider_startup():
    app = FastAPI()
    app.include_router(
        create_router(
            RivalMapRuntime(discovery=FakeDiscovery()),
            progressive_factory=FakeProgressiveRunner,
        )
    )

    response = TestClient(app).post(
        "/api/v1/runs/stream",
        json={
            "idea": "AI interview practice",
            "target_user": "job seekers",
            "problem": "practice interviews",
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-rivalmap-run-id"]
    assert "event: framing_started" in response.text
    assert "event: orchestration_complete" in response.text
    assert "raw_trace" not in response.text


def test_active_run_refinement_only_updates_whitelisted_market_brief_fields():
    registry = ActiveRunRegistry()
    registry.add(
        "run-1",
        MarketBrief(
            product_idea="AI interview practice",
            target_user="job seekers",
            problem="practice interviews",
        ),
    )
    app = FastAPI()
    app.include_router(
        create_router(
            RivalMapRuntime(discovery=FakeDiscovery()),
            progressive_factory=FakeProgressiveRunner,
            active_run_registry=registry,
        )
    )

    response = TestClient(app).post(
        "/api/v1/runs/run-1/refine",
        json={
            "exclusions": ["recruiting suites"],
            "competitive_scope": "consumer interview coaching",
            "priority_dimension": "feedback quality",
        },
    )

    assert response.status_code == 200
    assert response.json()["exclusions"] == ["recruiting suites"]
    assert response.json()["competitive_scope"] == "consumer interview coaching"
    assert response.json()["priority_dimension"] == "feedback quality"
    rejected = TestClient(app).post(
        "/api/v1/runs/run-1/refine",
        json={"problem": "replace the original problem"},
    )
    assert rejected.status_code == 422
