from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.response_envelope import ResponseEnvelopeMiddleware


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

    @app.get("/api/ping")
    async def ping():
        return {"pong": True}

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
