from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("th8.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log request/response with a request id.

    Keeps logic simple to match demo needs.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        start = time.perf_counter()

        try:
            response = await call_next(request)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            logger.info(
                "request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
                request_id,
                request.method,
                request.url.path,
                getattr(locals().get("response", None), "status_code", "NA"),
                duration_ms,
            )

        response.headers["x-request-id"] = request_id
        return response
