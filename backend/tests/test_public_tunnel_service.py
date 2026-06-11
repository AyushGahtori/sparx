import pytest

from app.config.settings import Settings
from app.core.errors import AppError
from app.services.public_tunnel_service import PublicTunnelService


def test_public_tunnel_health_returns_false_without_public_url():
    settings = Settings(_env_file=None, PUBLIC_BASE_URL=None)
    service = PublicTunnelService(settings)

    assert service.is_public_base_url_reachable() is False


def test_local_auto_tunnel_reports_clear_error_when_cloudflared_is_missing(tmp_path):
    settings = Settings(
        _env_file=None,
        PUBLIC_BASE_URL="https://stale-example.trycloudflare.com",
        CLOUDFLARED_PATH=str(tmp_path / "missing-cloudflared.exe"),
        PUBLIC_TUNNEL_HEALTH_TIMEOUT_SECONDS=2,
        PUBLIC_TUNNEL_START_TIMEOUT_SECONDS=5,
    )
    service = PublicTunnelService(settings)

    with pytest.raises(AppError) as exc_info:
        service.ensure_public_url_ready_for_call()

    assert exc_info.value.code == "cloudflared_missing"


def test_active_quick_tunnel_must_be_reachable_before_call(monkeypatch):
    settings = Settings(_env_file=None, PUBLIC_BASE_URL="https://stale-example.trycloudflare.com")
    service = PublicTunnelService(settings)
    started_with: list[bool] = []

    monkeypatch.setattr(service, "_has_active_quick_tunnel", lambda: True)
    monkeypatch.setattr(service, "is_public_base_url_reachable", lambda: False)

    def fake_start(*, wait_until_reachable: bool = False) -> str:
        started_with.append(wait_until_reachable)
        return settings.normalized_public_base_url or ""

    monkeypatch.setattr(service, "ensure_started_for_local_development", fake_start)

    with pytest.raises(AppError) as exc_info:
        service.ensure_public_url_ready_for_call()

    assert started_with == [True]
    assert exc_info.value.code == "public_base_url_unreachable"
