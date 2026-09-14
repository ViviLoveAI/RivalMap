"""RivalMap standalone ASGI application."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from rivalmap.api import create_router

load_dotenv()

app = FastAPI(title="RivalMap", version="0.1.0")
app.include_router(create_router())

_FRONTEND_DIR = Path(__file__).parent / "frontend"
app.mount("/assets", StaticFiles(directory=_FRONTEND_DIR), name="frontend-assets")


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {"ok": True, "service": "rivalmap"}
