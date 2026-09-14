"""Offline smoke server: real orchestration/SSE, mocked external research and models."""

import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from test_agents import _batch, _orchestrator, _summary
from test_market_intelligence import MockSemanticAnalyzer, MockStructuredAnalyzer

from rivalmap.agents import MarketIntelligenceAgent
from rivalmap.api import create_router
from rivalmap.contracts import AgentEvent, MarketBrief, ResearchBranch, ResearchEvent
from rivalmap.market_intelligence import MarketIntelligenceService


class ResearchFixture:
    def stream(self, brief, *, branches=None, wave=1):
        for count, name in enumerate(("alpha", "beta", "gamma"), 1):
            yield ResearchEvent(
                event="research_batch_updated",
                batch=_batch(name),
                summary=_summary(passed=count, branches=[ResearchBranch.DIRECT]),
            )
            time.sleep(1)
        time.sleep(8)  # The browser must inspect/compare before the stream completes.
        yield ResearchEvent(
            event="research_wave_complete",
            summary=_summary(passed=3, branches=[ResearchBranch.DIRECT]),
        )


def orchestrator():
    return _orchestrator(
        ResearchFixture(),
        intelligence=MarketIntelligenceAgent(
            MarketIntelligenceService(
                structured=MockStructuredAnalyzer(),
                semantic=MockSemanticAnalyzer(),
            )
        ),
    )


class runner:
    def stream(self, product_idea, *, target_user, problem):
        brief = MarketBrief(product_idea=product_idea, target_user=target_user, problem=problem)
        yield AgentEvent(
            event="market_brief_updated", run_status="FRAMING",
            message="Market brief prepared.", market_brief=brief,
        )
        yield from orchestrator().stream(brief)


app = FastAPI()
app.include_router(create_router(progressive_factory=runner))
frontend = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/assets", StaticFiles(directory=frontend))


@app.get("/")
def index():
    return FileResponse(frontend / "index.html")
