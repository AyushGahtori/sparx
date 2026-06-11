from app.core.errors import AppError


def _exception_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}".lower()


def is_firestore_quota_error(exc: Exception) -> bool:
    text = _exception_text(exc)
    markers = (
        "resourceexhausted",
        "resource exhausted",
        "quota exceeded",
        "quota",
        "429",
        "too many requests",
    )
    return any(marker in text for marker in markers)


def is_firestore_disabled_error(exc: Exception) -> bool:
    if isinstance(exc, AppError) and exc.code == "firestore_not_configured":
        return True
    text = _exception_text(exc)
    markers = (
        "service_disabled",
        "permissiondenied",
        "permission denied",
        "firestore api has not been used",
        "cloud firestore api has not been used",
        "firestore.googleapis.com",
    )
    return any(marker in text for marker in markers)


def is_firestore_transient_error(exc: Exception) -> bool:
    text = _exception_text(exc)
    markers = (
        "deadlineexceeded",
        "deadline exceeded",
        "unavailable",
        "service unavailable",
        "internalservererror",
        "internal server error",
        "aborted",
        "timeout",
        "timed out",
        "connection refused",
        "connection reset",
        "temporarily unavailable",
        "dns",
        "ssl",
        "network",
        "503",
        "500",
    )
    return any(marker in text for marker in markers)


def should_use_mongo_fallback(exc: Exception) -> bool:
    """Return whether a Firestore repository operation should continue through Mongo.

    This policy is intentionally scoped for repository Firestore try/except blocks.
    Business-level 4xx errors should keep raising, while unavailable, quota, auth,
    disabled, and unknown Firestore transport errors should fail over immediately.
    """
    if isinstance(exc, AppError):
        return exc.code in {"firestore_not_configured", "call_store_unavailable"} or exc.status_code >= 500
    return True
