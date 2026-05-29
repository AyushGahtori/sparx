import json

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.responses import build_success_payload


class ResponseEnvelopeMiddleware(BaseHTTPMiddleware):
    api_prefixes = ("/api",)
    excluded_paths = {"/api/openapi.json"}

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        if not self._should_wrap(request, response):
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        payload = json.loads(body.decode("utf-8")) if body else None
        if isinstance(payload, dict) and "success" in payload:
            return self._rebuild_response(payload, request, response, preserve_payload=True)

        return self._rebuild_response(payload, request, response, preserve_payload=False)

    def _should_wrap(self, request: Request, response: Response) -> bool:
        if request.scope.get("type") != "http":
            return False
        if request.url.path in self.excluded_paths:
            return False
        if not any(request.url.path.startswith(prefix) for prefix in self.api_prefixes):
            return False
        if response.status_code >= 400:
            return False
        if response.headers.get("X-Skip-Envelope") == "1":
            return False

        media_type = response.media_type or response.headers.get("content-type", "")
        return "application/json" in media_type

    @staticmethod
    def _rebuild_response(
        payload: object,
        request: Request,
        response: Response,
        *,
        preserve_payload: bool,
    ) -> JSONResponse:
        wrapped_payload = payload if preserve_payload else build_success_payload(request, payload)
        rebuilt = JSONResponse(
            status_code=response.status_code,
            content=wrapped_payload,
            background=response.background,
        )
        for key, value in response.headers.items():
            if key.lower() in {"content-length", "content-type"}:
                continue
            rebuilt.headers[key] = value
        return rebuilt
