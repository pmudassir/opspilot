"""Domain errors raised by services and translated to HTTP responses in one place."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    headers: dict[str, str] | None = None

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ForbiddenError(DomainError):
    """The caller can see the object but may not perform this action on it."""

    status_code = status.HTTP_403_FORBIDDEN


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, resource: str) -> None:
        super().__init__(f"{resource} not found")


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT


class UnprocessableError(DomainError):
    """Well-formed input that refers to something invalid, e.g. an unknown department_id."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT


async def _handle_domain_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _handle_domain_error)
