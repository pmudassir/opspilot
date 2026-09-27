"""Domain errors raised by services and translated to HTTP responses in one place."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, resource: str) -> None:
        super().__init__(f"{resource} not found")


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT


async def _handle_domain_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _handle_domain_error)
