from app.core.errors import AppError
from app.fallbacks.policy import (
    is_firestore_disabled_error,
    is_firestore_quota_error,
    is_firestore_transient_error,
    should_use_mongo_fallback,
)


def test_firestore_quota_errors_use_mongo_fallback() -> None:
    exc = RuntimeError("429 ResourceExhausted: quota exceeded")

    assert is_firestore_quota_error(exc)
    assert should_use_mongo_fallback(exc)


def test_firestore_disabled_errors_use_mongo_fallback() -> None:
    exc = RuntimeError("PERMISSIONDENIED firestore.googleapis.com service_disabled")

    assert is_firestore_disabled_error(exc)
    assert should_use_mongo_fallback(exc)


def test_firestore_transient_errors_use_mongo_fallback() -> None:
    exc = TimeoutError("DeadlineExceeded: service unavailable")

    assert is_firestore_transient_error(exc)
    assert should_use_mongo_fallback(exc)


def test_business_not_found_error_does_not_mask_repository_not_found() -> None:
    exc = AppError(status_code=404, code="call_not_found", message="Missing")

    assert not should_use_mongo_fallback(exc)


def test_unexpected_firestore_operation_error_uses_mongo_fallback() -> None:
    exc = RuntimeError("Firestore client raised an unexpected transport error")

    assert should_use_mongo_fallback(exc)
