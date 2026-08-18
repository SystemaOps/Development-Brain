"""API error envelope (Phase 23).

Standardizes error responses as ``{code, message, correlation_id, details}``.
Raw tracebacks are never exposed by default.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from brain.api.schemas import ErrorEnvelope


class BrainAPIError(Exception):
    """Application error with a stable code."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _correlation_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BrainAPIError)
    async def _brain_error(request: Request, exc: BrainAPIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorEnvelope(
                code=exc.code,
                message=exc.message,
                correlation_id=_correlation_id(request),
                details=exc.details,
            ).model_dump(mode="json"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorEnvelope(
                code=f"http_{exc.status_code}",
                message=str(exc.detail),
                correlation_id=_correlation_id(request),
            ).model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ErrorEnvelope(
                code="validation_error",
                message="request validation failed",
                correlation_id=_correlation_id(request),
                details={"errors": exc.errors()},
            ).model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=ErrorEnvelope(
                code="internal_error",
                message="internal server error",
                correlation_id=_correlation_id(request),
            ).model_dump(mode="json"),
        )
