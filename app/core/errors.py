from typing import Any

import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings


class CardicheckError(Exception):
    """Domain error with a machine-readable code the envelope can render."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def _error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "data": None,
        "error": {"code": code, "message": message, "details": details or {}},
        "meta": {},
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CardicheckError)
    async def on_cardicheck_error(_request, exc: CardicheckError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details),
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def on_http_exception(_request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "UNAUTHORIZED",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
        }.get(exc.status_code, f"HTTP_{exc.status_code}")
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(status_code=exc.status_code, content=_error_body(code, message))

    def _json_safe(err: dict[str, Any]) -> dict[str, Any]:
        # Pydantic errors can carry non-serializable context (model_validator
        # raises embed the ValueError in `ctx`) — the error envelope must not
        # be able to crash its own response, so stringify anything non-primitive.
        ctx = err.get("ctx") or {}
        safe_ctx = {k: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v)) for k, v in ctx.items()}
        out = dict(err)
        out["ctx"] = safe_ctx
        return out

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(_request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body("VALIDATION_ERROR", "request validation failed", {"errors": [_json_safe(e) for e in exc.errors()]}),
        )

    @app.exception_handler(Exception)
    async def on_unhandled_error(_request, exc: Exception) -> JSONResponse:
        # Never call the log silent: debug mode leaks the message to the client,
        # but prod must still trace the failure server-side.
        logging.getLogger("uvicorn.error").exception("unhandled error", exc_info=exc)
        settings = get_settings()
        message = str(exc) if settings.debug else "internal server error"
        return JSONResponse(status_code=500, content=_error_body("INTERNAL_ERROR", message))