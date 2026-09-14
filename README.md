# RivalMap

RivalMap is the physically separate competitive-intelligence capability extracted from MarketCompass.

It focuses on one path:

```text
Input → Exa discovery → Evidence → MarketStructure → BaseMap → Analysis → RivalMapState
```

This is a temporary product/runtime separation for hackathon development, not a permanent fork. The stable future integration boundary is:

- input: `RivalMapRequest`
- output: `RivalMapState`

MarketCompass should later invoke RivalMap through that boundary instead of importing RivalMap runtime internals.

## What was extracted from MarketCompass

Copied/adapted framework-neutral pieces from the frozen MarketCompass baseline `ca1356c`:

- evidence/provenance contracts
- product profile, relation, cluster and position contracts
- `MarketStructure`
- renderer-independent `ProductMap` / base-map contracts
- degradation levels: `FULL / D1 / D2 / D3 / FAILED`
- `RivalMapState`
- deterministic structure builder and base-map derivation
- compact evidence view helpers
- model/discovery service interfaces
- typed SSE-style runtime events
- Exa discovery adapter shape

## What remains MarketCompass-only

Not copied:

- MarketCompass LangGraph workflow
- full User Model / World Model memory roadmap
- Admin surface
- ADK legacy runtime
- collaborative exploration governance loop
- 3D/OpenWorld UI prototype
- MarketCompass frontend

## Future shared-core candidates

After RivalMap contracts stabilize, these should become shared instead of copied:

- contracts: `EvidenceItem`, `ProductProfile`, `MarketStructure`, `ProductMap`, `RivalMapState`
- deterministic structure/base-map builder
- compact evidence view
- provider/router interfaces
- degradation semantics

## Run locally

```bash
cd /Users/weiyuliu/Downloads/RivalMap
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
# add EXA_API_KEY if using live discovery
uvicorn server:app --reload --host 127.0.0.1 --port 8876
```

Health check:

```bash
curl http://127.0.0.1:8876/health
```

Open `http://127.0.0.1:8876/` for the progressive RivalMap frontend. It consumes
the Bedrock vertical slice through `POST /api/v1/runs/stream`; the original
`POST /api/runs` and `POST /api/runs/stream` contracts remain unchanged.
Use `http://127.0.0.1:8876/?demo=1` for the real-provider hackathon demo flow.
The completed map can be exported directly from the browser as SVG or PNG.

Run tests:

```bash
python -m pytest -q
ruff check .
```

## API

`POST /api/runs`

```json
{
  "idea": "帮助留学生练习英语面试的工具",
  "target_user": "留学生",
  "problem": "面试表达紧张",
  "exclusions": ["少儿"]
}
```

Returns a `RivalMapState`.

`POST /api/runs/stream` returns server-sent events for progress instrumentation.
