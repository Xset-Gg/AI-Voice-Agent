from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import log


class AppError(Exception):
    """Domain error with a stable machine-readable code."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, code: str = "bad_request", status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        if status_code is not None:
            self.status_code = status_code


class NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, what: str = "Resource"):
        super().__init__(f"{what} not found", code="not_found")


class Forbidden(AppError):
    status_code = status.HTTP_403_FORBIDDEN

    def __init__(self, message: str = "You do not have permission to perform this action"):
        super().__init__(message, code="forbidden")


class Conflict(AppError):
    status_code = status.HTTP_409_CONFLICT

    def __init__(self, message: str):
        super().__init__(message, code="conflict")


class IntegrationError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY

    def __init__(self, message: str):
        super().__init__(message, code="integration_error")


def _body(code: str, message: str, request: Request, details=None) -> dict:
    body = {"error": {"code": code, "message": message, "request_id": getattr(request.state, "request_id", None)}}
    if details is not None:
        body["error"]["details"] = details
    return body


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, request), status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            _body("http_error", str(exc.detail), request), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(_body("validation_error", "Invalid request", request, details), status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled_error", path=request.url.path)
        return JSONResponse(_body("internal_error", "Internal server error", request), status_code=500)
