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


def should_use_mongo_fallback(exc: Exception) -> bool:
    if isinstance(exc, AppError) and exc.code == "firestore_not_configured":
        return True
    return is_firestore_quota_error(exc)
