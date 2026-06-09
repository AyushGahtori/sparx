from app.core.errors import AppError


def is_firestore_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "resourceexhausted",
        "quota exceeded",
        "429",
        "too many requests",
    )
    return any(marker in text for marker in markers)


def is_firestore_disabled_error(exc: Exception) -> bool:
    if isinstance(exc, AppError) and exc.code == "firestore_not_configured":
        return True
    text = str(exc).lower()
    markers = (
        "service_disabled",
        "permissiondenied",
        "permission denied",
        "firestore api has not been used",
        "cloud firestore api has not been used",
        "firestore.googleapis.com",
    )
    return any(marker in text for marker in markers)


def should_use_mongo_fallback(exc: Exception) -> bool:
    return is_firestore_disabled_error(exc) or is_firestore_quota_error(exc)
