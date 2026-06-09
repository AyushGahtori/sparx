from app.config.settings import Settings


def test_firebase_is_disabled_by_default_even_when_credentials_exist():
    settings = Settings(
        _env_file=None,
        AUTH_REQUIRED=False,
        FIREBASE_CREDENTIALS_PATH="firebase-admin.json",
    )

    assert settings.firebase_enabled is False
    assert settings.has_firebase_admin_config is True
    assert settings.has_firebase_config is False
    assert settings.mongodb_fallback_enabled is True
    assert settings.resolved_auth_required is False


def test_ai_runner_can_run_while_call_dispatch_runners_are_disabled():
    settings = Settings(
        _env_file=None,
        RUN_BACKGROUND_RUNNERS=False,
        RUN_CALLBACK_DISPATCH_RUNNER=None,
        RUN_CAMPAIGN_DISPATCH_RUNNER=None,
    )

    assert settings.resolved_run_ai_background_runner is True
    assert settings.resolved_run_call_dispatch_runners is False
    assert settings.resolved_run_callback_dispatch_runner is False
    assert settings.resolved_run_campaign_dispatch_runner is False


def test_explicit_runner_switches_override_legacy_background_switch():
    settings = Settings(
        _env_file=None,
        RUN_BACKGROUND_RUNNERS=False,
        RUN_AI_BACKGROUND_RUNNER=False,
        RUN_CALL_DISPATCH_RUNNERS=True,
        RUN_CALLBACK_DISPATCH_RUNNER=None,
        RUN_CAMPAIGN_DISPATCH_RUNNER=None,
    )

    assert settings.resolved_run_ai_background_runner is False
    assert settings.resolved_run_call_dispatch_runners is True
    assert settings.resolved_run_callback_dispatch_runner is True
    assert settings.resolved_run_campaign_dispatch_runner is True


def test_callback_dispatch_can_run_while_campaign_dispatch_is_disabled():
    settings = Settings(
        _env_file=None,
        RUN_BACKGROUND_RUNNERS=False,
        RUN_CALL_DISPATCH_RUNNERS=False,
        RUN_CALLBACK_DISPATCH_RUNNER=True,
        RUN_CAMPAIGN_DISPATCH_RUNNER=False,
    )

    assert settings.resolved_run_ai_background_runner is True
    assert settings.resolved_run_call_dispatch_runners is False
    assert settings.resolved_run_callback_dispatch_runner is True
    assert settings.resolved_run_campaign_dispatch_runner is False
