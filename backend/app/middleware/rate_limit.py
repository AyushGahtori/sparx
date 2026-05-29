from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.settings import Settings
from app.core.responses import build_error_payload


@dataclass(frozen=True)
class RateLimitRule:
    scope: str
    limit: int
    window_seconds: int


class RateLimiter:
    def __init__(self) -> None:
        self._entries: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, int, float]:
        now = monotonic()
        boundary = now - window_seconds

        with self._lock:
            window = self._entries.setdefault(key, deque())
            while window and window[0] <= boundary:
                window.popleft()

            if len(window) >= limit:
                retry_after = max(window_seconds - (now - window[0]), 1.0)
                remaining = 0
                return False, remaining, retry_after

            window.append(now)
            remaining = max(limit - len(window), 0)
            return True, remaining, float(window_seconds)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings
        self.rate_limiter = RateLimiter()

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.settings.rate_limit_enabled:
            return await call_next(request)

        rule = self._match_rule(request)
        if rule is None:
            return await call_next(request)

        client_identifier = self._resolve_client_identifier(request)
        allowed, remaining, retry_after = self.rate_limiter.check(
            f"{rule.scope}:{client_identifier}",
            limit=rule.limit,
            window_seconds=rule.window_seconds,
        )

        if not allowed:
            response = JSONResponse(
                status_code=429,
                content=build_error_payload(
                    request,
                    message="Rate limit exceeded. Please slow down and try again shortly.",
                    error_code="rate_limit_exceeded",
                    details={
                        "scope": rule.scope,
                        "limit": rule.limit,
                        "window_seconds": rule.window_seconds,
                        "retry_after_seconds": int(retry_after),
                    },
                ),
            )
            response.headers["Retry-After"] = str(int(retry_after))
            response.headers["X-RateLimit-Limit"] = str(rule.limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Scope"] = rule.scope
            return response

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(rule.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Scope"] = rule.scope
        return response

    def _match_rule(self, request: Request) -> RateLimitRule | None:
        path = request.url.path
        method = request.method.upper()

        if not path.startswith(self.settings.api_v1_prefix):
            return None
        if method == "OPTIONS":
            return None
        if path.startswith(f"{self.settings.api_v1_prefix}/webhooks"):
            return None
        if path in {"/docs", "/redoc", "/openapi.json", f"{self.settings.api_v1_prefix}/health"}:
            return None

        if method == "POST" and path == f"{self.settings.api_v1_prefix}/calls/individual":
            return RateLimitRule("manual_call", self.settings.call_rate_limit_per_minute, 60)

        if method == "POST" and path.endswith("/start") and path.startswith(f"{self.settings.api_v1_prefix}/campaigns/"):
            return RateLimitRule("campaign_start", self.settings.campaign_start_rate_limit_per_minute, 60)

        return RateLimitRule("general_api", self.settings.general_rate_limit_per_minute, 60)

    @staticmethod
    def _resolve_client_identifier(request: Request) -> str:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        if request.client is not None:
            return request.client.host
        return "unknown"
