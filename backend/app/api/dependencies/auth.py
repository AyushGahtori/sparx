from fastapi import Request

from app.core.errors import AppError
from app.services.firebase_auth_service import AuthenticatedUser


def get_current_user(request: Request) -> AuthenticatedUser:
    user = getattr(request.state, "user", None)
    if user is None:
        raise AppError(
            status_code=401,
            code="auth_missing",
            message="A Firebase bearer token is required to access this endpoint.",
        )
    return user
