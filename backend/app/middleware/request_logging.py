import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.settings import Settings
from app.core.logging import get_logger
from app.core.request_context import reset_request_context, set_request_context
from app.utils.network import resolve_client_ip

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        client_ip = resolve_client_ip(request, trust_proxy_headers=self.settings.trust_proxy_headers)
        request.state.request_id = request_id
        request.state.client_ip = client_ip
        start_time = time.perf_counter()
        context_tokens = set_request_context(request_id, client_ip)

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(
                "Request failed | method=%s | path=%s | request_id=%s | duration_ms=%.2f",
                request.method,
                request.url.path,
                request_id,
                duration_ms,
            )
            reset_request_context(context_tokens)
            raise

        duration_ms = (time.perf_counter() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"

        logger.info(
            "Request completed | method=%s | path=%s | status_code=%s | request_id=%s | duration_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            request_id,
            duration_ms,
        )
        reset_request_context(context_tokens)
        return response
