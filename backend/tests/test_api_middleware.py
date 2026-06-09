from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.core.errors import AppError
from app.core.handlers import register_exception_handlers
from app.middleware.firebase_auth import FirebaseAuthMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.response_envelope import ResponseEnvelopeMiddleware
from app.services.firebase_auth_service import AuthenticatedUser


def build_test_app() -> FastAPI:
    settings = Settings(
        _env_file=None,
        GENERAL_RATE_LIMIT_PER_MINUTE=2,
        CALL_RATE_LIMIT_PER_MINUTE=1,
        CAMPAIGN_START_RATE_LIMIT_PER_MINUTE=1,
    )
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(ResponseEnvelopeMiddleware)
    register_exception_handlers(app)

    @app.get("/api/ping")
    async def ping():
        return {"pong": True}

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    return app


class DummyAuthService:
    def verify_authorization_header(self, authorization_header):
        if not authorization_header:
            raise AppError(status_code=401, code="auth_missing", message="Missing auth.")
        if authorization_header != "Bearer test-token":
            raise AppError(status_code=401, code="auth_invalid_token", message="Invalid auth.")
        return AuthenticatedUser(
            uid="user_123",
            email="operator@example.com",
            name="Operator",
            picture=None,
            email_verified=True,
            sign_in_provider="google.com",
            role="operator",
            claims={},
        )


def build_auth_test_app() -> FastAPI:
    settings = Settings(
        _env_file=None,
        AUTH_REQUIRED=True,
        FIREBASE_CREDENTIALS_PATH="firebase-admin.json",
    )
    app = FastAPI()
    app.add_middleware(
        FirebaseAuthMiddleware,
        settings=settings,
        auth_service=DummyAuthService(),
    )
    app.add_middleware(ResponseEnvelopeMiddleware)
    register_exception_handlers(app)

    @app.get("/api/secure")
    async def secure():
        return {"secure": True}

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    return app


def test_response_envelope_wraps_success_payload():
    client = TestClient(build_test_app())

    response = client.get("/api/ping")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"] == {"pong": True}


def test_rate_limiter_blocks_excess_requests():
    client = TestClient(build_test_app())

    assert client.get("/api/ping").status_code == 200
    assert client.get("/api/ping").status_code == 200
    blocked_response = client.get("/api/ping")

    assert blocked_response.status_code == 429
    payload = blocked_response.json()
    assert payload["success"] is False
    assert payload["error_code"] == "rate_limit_exceeded"


def test_firebase_auth_middleware_allows_public_health_without_token():
    client = TestClient(build_auth_test_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["data"] == {"ok": True}


def test_firebase_auth_middleware_requires_bearer_token_for_protected_routes():
    client = TestClient(build_auth_test_app())

    response = client.get("/api/secure")

    assert response.status_code == 401
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_code"] == "auth_missing"


def test_firebase_auth_middleware_accepts_valid_bearer_token():
    client = TestClient(build_auth_test_app())

    response = client.get("/api/secure", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json()["data"] == {"secure": True}
