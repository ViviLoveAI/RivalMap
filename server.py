"""RivalMap standalone ASGI application."""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI

from rivalmap.api import create_router

load_dotenv()

app = FastAPI(title="RivalMap", version="0.1.0")
app.include_router(create_router())


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {"ok": True, "service": "rivalmap"}
