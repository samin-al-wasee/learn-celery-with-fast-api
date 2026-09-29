"""API gateway: one public base URL in front of the monolith and the services (M6).

Run:  uvicorn services.gateway.main:app --port 8080
Routes: /api/v1/notifications* -> notifications service; everything else -> monolith.
(WebSocket chat is not proxied; clients connect to the monolith directly.)
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.request_id import HEADER, install_request_id, request_id_var

HOP_BY_HOP = {"host", "connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "content-length"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # M6: one pooled client for the gateway's lifetime; a client per request paid a fresh
    # TCP connection on every call (+8.4 ms measured).
    app.state.client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=2.0),
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
    )
    yield
    await app.state.client.aclose()


app = FastAPI(title="gateway", lifespan=lifespan)
install_request_id(app, "gateway")


def upstream_for(path: str) -> str:
    settings = get_settings()
    if path.startswith("/api/v1/notifications"):
        return settings.gateway_notifications_url
    return settings.gateway_monolith_url


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"data": None, "meta": {}, "error": {"code": code, "message": message}})


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request) -> Response:
    url = upstream_for("/" + path) + "/" + path
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    headers[HEADER] = request_id_var.get()
    try:
        r = await request.app.state.client.request(
            request.method, url, params=request.query_params, headers=headers, content=await request.body()
        )
    except (httpx.ConnectTimeout, httpx.ConnectError):
        # M6: couldn't connect at all -> unavailable (502). On Windows a refused connect shows up
        # as a ConnectTimeout after ~2s, which must not be reported as a slow upstream.
        return _error(502, "UPSTREAM_UNAVAILABLE", "upstream service unavailable")
    except httpx.TimeoutException:
        return _error(504, "UPSTREAM_TIMEOUT", "upstream service timed out")
    except httpx.TransportError:
        return _error(502, "UPSTREAM_UNAVAILABLE", "upstream service unavailable")
    out = {k: v for k, v in r.headers.items() if k.lower() not in HOP_BY_HOP | {"content-encoding", HEADER.lower()}}
    return Response(content=r.content, status_code=r.status_code, headers=out)
