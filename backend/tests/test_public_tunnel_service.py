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
    started_with: list[tuple[bool, bool]] = []

    monkeypatch.setattr(service, "_has_active_quick_tunnel", lambda: True)
    monkeypatch.setattr(service, "is_public_base_url_reachable", lambda: False)

    def fake_start(*, wait_until_reachable: bool = False, force_refresh: bool = False) -> str:
        started_with.append((wait_until_reachable, force_refresh))
        return settings.normalized_public_base_url or ""

    monkeypatch.setattr(service, "ensure_started_for_local_development", fake_start)

    with pytest.raises(AppError) as exc_info:
        service.ensure_public_url_ready_for_call()

    assert started_with == [(True, True)]
    assert exc_info.value.code == "public_base_url_unreachable"


def test_slow_cloudflare_tunnel_gets_extra_readiness_probe(monkeypatch):
    settings = Settings(
        _env_file=None,
        PUBLIC_BASE_URL="https://slow-example.trycloudflare.com",
        PUBLIC_TUNNEL_START_TIMEOUT_SECONDS=5,
    )
    service = PublicTunnelService(settings)
    reachability_results = iter([False, True])

    def fake_start(*, wait_until_reachable: bool = False, force_refresh: bool = False) -> str:
        raise AppError(
            status_code=503,
            code="public_base_url_unreachable",
            message="Cloudflared started a tunnel but the public URL was not reachable in time.",
            details={"public_base_url": settings.normalized_public_base_url},
        )

    monkeypatch.setattr(service, "ensure_started_for_local_development", fake_start)
    monkeypatch.setattr(service, "is_public_base_url_reachable", lambda: next(reachability_results))
    monkeypatch.setattr("app.services.public_tunnel_service.time.sleep", lambda _seconds: None)

    service.ensure_public_url_ready_for_call()


def test_quick_tunnel_with_public_dns_passes_when_local_resolver_fails(monkeypatch):
    settings = Settings(_env_file=None, PUBLIC_BASE_URL="https://dns-ok.trycloudflare.com")
    service = PublicTunnelService(settings)

    monkeypatch.setattr(service, "is_public_base_url_reachable", lambda: False)
    monkeypatch.setattr(service, "_is_managed_tunnel_running", lambda: True)
    monkeypatch.setattr(service, "_has_registered_tunnel_connection", lambda: True)
    monkeypatch.setattr(service, "_is_local_origin_reachable", lambda: True)
    monkeypatch.setattr(service, "_is_public_dns_resolvable", lambda _base_url: True)

    service.ensure_public_url_ready_for_call()
