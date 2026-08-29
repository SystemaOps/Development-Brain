"""Correlation middleware (Phase 23).

Accepts a valid incoming correlation ID or generates one, stores it in the
request scope, and returns it in the response header.  Downstream commands,
events, and logs use the same correlation id.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_HEADER = "X-Correlation-ID"
CORRELATION_SCOPE = "correlation_id"

DispatchCallable = Callable[[Request], Awaitable[Response]]


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: DispatchCallable) -> Response:
        incoming = request.headers.get(CORRELATION_HEADER)
        correlation_id = _parse_or_generate(incoming)
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers[CORRELATION_HEADER] = correlation_id
        return response


def _parse_or_generate(value: str | None) -> str:
    if value:
        try:
            return str(uuid.UUID(value))
        except ValueError:
            pass
    return str(uuid.uuid4())
