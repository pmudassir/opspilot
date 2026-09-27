from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse

from app.config import get_settings

STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def reject_cross_origin_writes(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """CSRF defense in depth (alongside SameSite=Lax cookies).

    Browsers attach an Origin header to cross-origin writes; reject unknown origins.
    Requests without Origin (curl, server-to-server) carry no ambient browser cookies
    from another site, so they are allowed through.
    """
    origin = request.headers.get("origin")
    if (
        request.method in STATE_CHANGING_METHODS
        and origin is not None
        and origin not in get_settings().allowed_origins
    ):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "Cross-origin request rejected"},
        )
    return await call_next(request)
