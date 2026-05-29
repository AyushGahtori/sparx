from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.responses import build_error_payload

logger = get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        log_message = "Application error | code=%s | status_code=%s | path=%s | message=%s"
        if exc.status_code >= 500:
            logger.error(log_message, exc.code, exc.status_code, request.url.path, exc.message)
        else:
            logger.warning(log_message, exc.code, exc.status_code, request.url.path, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_payload(
                request,
                message=exc.message,
                error_code=exc.code,
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=build_error_payload(
                request,
                message="The request payload or parameters are invalid.",
                error_code="validation_error",
                details=exc.errors(),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_payload(
                request,
                message=str(exc.detail),
                error_code="http_error",
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled application error: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=build_error_payload(
                request,
                message="An unexpected server error occurred.",
                error_code="internal_server_error",
            ),
        )
