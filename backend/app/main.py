"""FastAPI application.

Run locally:  uvicorn app.main:app --reload --port 8000
Production:   uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .errors import install_error_handlers
from .logging_config import configure_logging
from .routers import (
    ai_providers,
    analysis,
    assistant,
    constraints,
    documents,
    exports,
    financials,
    firms,
    funds,
    health,
    households,
    workspace,
)

log = logging.getLogger("slipslopes.http")


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="OndhoDeck API", version=health.API_VERSION,
        description="Contractual liquidity intelligence: document extraction, deterministic cash-flow "
                    "simulation, reverse stress testing and prevention planning.",
        docs_url="/docs", redoc_url=None, openapi_url="/openapi.json")
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"], expose_headers=["X-Request-ID"],
        max_age=600)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid[:64]
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        # Method, path template-free path, status and latency only: never bodies, tokens or amounts.
        log.info("%s %s %s %.0fms rid=%s", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - start) * 1000, request.state.request_id)
        return response

    for r in (health.router, households.router, financials.router, documents.router, constraints.router,
              analysis.router, exports.router, ai_providers.router, firms.router, funds.router, workspace.router,
              assistant.router):
        app.include_router(r, prefix="/api/v1")
    return app


app = create_app()
