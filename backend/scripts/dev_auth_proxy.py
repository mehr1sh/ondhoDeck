"""Development-only gateway: exposes a local Supabase Auth (GoTrue) server under /auth/v1.

Hosted Supabase serves Auth at https://<project>.supabase.co/auth/v1; the supabase-js client
expects that layout. GoTrue itself serves routes at its root, so locally this tiny proxy adds the
prefix and CORS headers for the frontend origin. Never deploy this.

    python scripts/dev_auth_proxy.py   # listens on :54321, forwards to GOTRUE_URL (default :9999)
"""
from __future__ import annotations

import os

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

GOTRUE = os.environ.get("GOTRUE_URL", "http://localhost:9999")
ORIGINS = {o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")}
HOP = {"host", "content-length", "connection", "accept-encoding", "transfer-encoding"}


def _cors(request: Request, response: Response) -> Response:
    origin = request.headers.get("origin")
    if origin in ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = (
            "authorization, apikey, content-type, x-client-info, x-supabase-api-version")
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    return response


async def proxy(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _cors(request, Response(status_code=204))
    path = request.path_params.get("path", "")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        upstream = await client.request(request.method, f"{GOTRUE}/{path}", params=request.query_params,
                                        headers=headers, content=await request.body())
    out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP | {"content-encoding"}}
    # Rewrite verification redirects so they keep pointing at this gateway.
    if "location" in out_headers:
        out_headers["location"] = out_headers["location"].replace(GOTRUE, "http://localhost:54321/auth/v1")
    return _cors(request, Response(upstream.content, status_code=upstream.status_code, headers=out_headers))


async def health(request: Request) -> Response:
    return JSONResponse({"gateway": "ok", "upstream": GOTRUE})


app = Starlette(routes=[Route("/health", health),
                        Route("/auth/v1/{path:path}", proxy, methods=["GET", "POST", "PUT", "PATCH", "DELETE",
                                                                         "OPTIONS"])])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "54321")), log_level="warning")
