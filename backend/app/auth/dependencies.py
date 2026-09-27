from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status

from app.auth import service
from app.db import SessionDep
from app.users.models import User

SESSION_COOKIE_NAME = "opspilot_session"

SessionTokenDep = Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)]


async def get_current_user(session: SessionDep, token: SessionTokenDep = None) -> User:
    user = await service.get_user_by_session_token(session, token) if token else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
