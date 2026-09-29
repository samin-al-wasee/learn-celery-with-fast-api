import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import FastAPI, Request, Response

HEADER = "X-Request-ID"
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
logger = logging.getLogger("uvicorn.error")


def install_request_id(app: FastAPI, service: str) -> None:
    """Accept or mint an X-Request-ID, expose it to handlers, echo it back, log one line per request."""

    @app.middleware("http")
    async def _request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # M6: the id minted at the edge (gateway) is reused by every service it touches, so one
        # grep across all services' logs finds the whole path of a single request.
        rid = request.headers.get(HEADER) or uuid.uuid4().hex
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[HEADER] = rid
        logger.info(
            "service=%s request_id=%s %s %s -> %s %.1fms",
            service, rid, request.method, request.url.path, response.status_code, (time.perf_counter() - t0) * 1000,
        )
        return response
