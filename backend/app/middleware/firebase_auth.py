from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.settings import Settings
from app.core.errors import AppError
from app.core.responses import build_error_payload
from app.services.firebase_auth_service import FirebaseAuthService, get_firebase_auth_service


class FirebaseAuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        settings: Settings,
        auth_service: FirebaseAuthService | None = None,
    ) -> None:
        super().__init__(app)
        self.settings = settings
        self.auth_service = auth_service or get_firebase_auth_service()

    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.user = None

        if request.scope.get("type") != "http":
            return await call_next(request)
        if request.method.upper() == "OPTIONS":
            return await call_next(request)
        if not request.url.path.startswith(self.settings.api_v1_prefix):
            return await call_next(request)

        authorization_header = request.headers.get("Authorization")
        if not authorization_header and request.url.path == f"{self.settings.api_v1_prefix}/events/stream":
            event_token = request.query_params.get("token")
            if event_token:
                authorization_header = f"Bearer {event_token}"
        path_is_public = self._is_public_path(request.url.path)

        if not self.settings.resolved_auth_required and not authorization_header:
            return await call_next(request)
        if path_is_public and not authorization_header:
            return await call_next(request)

        try:
            request.state.user = self.auth_service.verify_authorization_header(authorization_header)
        except AppError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content=build_error_payload(
                    request,
                    message=exc.message,
                    error_code=exc.code,
                    details=exc.details,
                ),
            )
        return await call_next(request)

    def _is_public_path(self, path: str) -> bool:
        public_exact_paths = {
            f"{self.settings.api_v1_prefix}/health",
            f"{self.settings.api_v1_prefix}/health/firebase",
            f"{self.settings.api_v1_prefix}/health/gemma",
            f"{self.settings.api_v1_prefix}/system/health",
            f"{self.settings.api_v1_prefix}/twilio",
            f"{self.settings.api_v1_prefix}/twilio/health",
            f"{self.settings.api_v1_prefix}/deepgram",
            f"{self.settings.api_v1_prefix}/deepgram/health",
            f"{self.settings.api_v1_prefix}/auth/google/callback",
        }
        if path in public_exact_paths:
            return True
        return path.startswith(f"{self.settings.api_v1_prefix}/webhooks")
