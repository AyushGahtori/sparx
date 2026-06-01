from datetime import datetime, timezone

from app.config.settings import Settings
from app.services.retry_service import RetryService


def test_retry_service_applies_configured_retry_schedule():
    settings = Settings(
        _env_file=None,
        CALL_MAX_AUTO_CALLS=3,
        CALL_RETRY_INTERVAL_MINUTES=10,
    )
    service = RetryService(settings=settings)
    reference_time = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)

    first_attempt = service.build_retry_decision(0, "failed", reference_time)
    second_attempt = service.build_retry_decision(1, "failed", reference_time)
    third_attempt = service.build_retry_decision(2, "failed", reference_time)
    final_attempt = service.build_retry_decision(3, "failed", reference_time)

    assert first_attempt.retry_count == 1
    assert first_attempt.final_status == "retry_scheduled"
    assert first_attempt.backoff_seconds == 600

    assert second_attempt.retry_count == 2
    assert second_attempt.final_status == "retry_scheduled"
    assert second_attempt.backoff_seconds == 600

    assert third_attempt.retry_count == 3
    assert third_attempt.final_status == "retry_scheduled"
    assert third_attempt.backoff_seconds == 600

    assert final_attempt.retry_count == 3
    assert final_attempt.final_status == "permanently_failed"
    assert final_attempt.next_retry_time is None


def test_retry_service_does_not_retry_non_retryable_status():
    service = RetryService()
    reference_time = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)

    decision = service.build_retry_decision(0, "completed", reference_time)

    assert decision.retry_count == 0
    assert decision.final_status == "completed"
    assert decision.next_retry_time is None
