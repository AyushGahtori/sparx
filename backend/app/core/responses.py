from fastapi import Request

from app.utils.time import utc_now_iso


def build_success_payload(
    request: Request,
    data: object,
    *,
    message: str = "Request completed successfully.",
) -> dict[str, object]:
    return {
        "success": True,
        "message": message,
        "data": data,
        "request_id": getattr(request.state, "request_id", None),
        "timestamp": utc_now_iso(),
    }


def build_error_payload(
    request: Request,
    *,
    message: str,
    error_code: str,
    details: object | None = None,
) -> dict[str, object]:
    return {
        "success": False,
        "error": message,
        "error_code": error_code,
        "details": details or {},
        "request_id": getattr(request.state, "request_id", None),
        "path": request.url.path,
        "timestamp": utc_now_iso(),
    }
