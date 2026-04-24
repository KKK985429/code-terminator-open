from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from structlog.contextvars import bind_contextvars, clear_contextvars

from services.shared.event_log import body_for_log, write_event, write_exception_event


def install_request_logging(app: FastAPI, *, service: str) -> None:
    logger = structlog.get_logger(service)

    @app.middleware("http")
    async def request_logging_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex
        body = await request.body()
        request.state.trace_id = trace_id

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(request.scope, receive)
        request.state.trace_id = trace_id
        bind_contextvars(
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
            service=service,
        )
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.error(
                "request_unhandled_exception",
                trace_id=trace_id,
                status_code=500,
                latency_ms=latency_ms,
                exc_info=True,
            )
            write_exception_event(
                service=service,
                level="error",
                event="service_exception",
                exc=exc,
                trace_id=trace_id,
                source="service",
                method=request.method,
                path=request.url.path,
                query=request.url.query,
                status_code=500,
                latency_ms=latency_ms,
                request_body=body_for_log(body, request.headers.get("content-type")),
            )
            clear_contextvars()
            raise

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["x-trace-id"] = trace_id
        level = "info"
        if response.status_code >= 500:
            level = "error"
        elif response.status_code >= 400:
            level = "warning"
        getattr(logger, level)(
            "request_completed",
            trace_id=trace_id,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        write_event(
            service=service,
            level=level,
            event="service_request",
            source="service",
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
            query=request.url.query,
            status_code=response.status_code,
            latency_ms=latency_ms,
            request_body=body_for_log(body, request.headers.get("content-type")),
        )
        clear_contextvars()
        return response
