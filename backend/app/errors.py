"""Consistent JSON error responses. Internal details and tracebacks never reach clients."""
from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("slipslopes.errors")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None,
                 headers: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details, self.headers = status, code, message, details, headers


def _body(code: str, message: str, request_id: str, details: object | None = None) -> dict:
    err: dict = {"code": code, "message": message, "request_id": request_id}
    if details is not None:
        err["details"] = details
    return {"error": err}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message, _request_id(request), exc.details), status_code=exc.status,
                            headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg", "")} for e in exc.errors()]
        return JSONResponse(_body("validation_error", "Some fields are invalid.", _request_id(request), details),
                            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        message = "Not found." if exc.status_code == 404 else str(exc.detail)
        return JSONResponse(_body(code, message, _request_id(request)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        rid = _request_id(request)
        log.exception("unhandled error request_id=%s path=%s", rid, request.url.path)
        return JSONResponse(_body("internal_error", "Something went wrong. Please try again.", rid), status_code=500)
