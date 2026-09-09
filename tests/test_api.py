from fastapi import FastAPI
from fastapi.testclient import TestClient

from rivalmap.api import create_router
from rivalmap.contracts import EvidenceItem, EvidenceRelation, Source, SourceQuality
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
