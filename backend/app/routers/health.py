"""Liveness and readiness (no authentication)."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ..api_schemas import HealthOut
from ..config import get_settings
from ..db import get_engine
from ..engine.simulator import ENGINE_VERSION

router = APIRouter(tags=["health"])
API_VERSION = "1.0.0"


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(status="ok", version=API_VERSION, checks={"engine": ENGINE_VERSION})


@router.get("/ready", response_model=HealthOut, responses={503: {"model": HealthOut}})
def ready():
    settings = get_settings()
    checks: dict[str, str] = {}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        checks["database"] = f"ok (migration {head})"
    except Exception:
        checks["database"] = "unavailable"
    if settings.celery_task_always_eager:
        checks["queue"] = "eager (test mode)"
    else:
        try:
            import redis
            redis.Redis.from_url(settings.redis_url, socket_timeout=1, socket_connect_timeout=1).ping()
            checks["queue"] = "ok"
        except Exception:
            checks["queue"] = "unavailable"
    checks["storage"] = settings.storage_backend
    checks["llm"] = settings.llm_provider if settings.llm_configured else "not configured (rule-based extraction)"
    ok = checks["database"].startswith("ok") and checks["queue"] != "unavailable"
    body = HealthOut(status="ok" if ok else "unavailable", version=API_VERSION, checks=checks)
    return JSONResponse(body.model_dump(), status_code=200 if ok else 503)
