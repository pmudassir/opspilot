from datetime import timedelta

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.dependencies import SESSION_COOKIE_NAME, CurrentUserDep, SessionTokenDep
from app.auth.schemas import (
    LoginRequest,
    MembershipOut,
    MeResponse,
    SignupRequest,
    UserOut,
)
from app.config import Settings, SettingsDep
from app.db import SessionDep
from app.organizations.service import list_active_memberships
from app.users.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

INVALID_CREDENTIALS_DETAIL = "Invalid email or password"


def _session_ttl(settings: Settings) -> timedelta:
    return timedelta(hours=settings.session_ttl_hours)


def _set_session_cookie(
    response: Response, issued: service.IssuedSession, settings: Settings
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=issued.token,
        max_age=settings.session_ttl_hours * 3600,
        expires=issued.expires_at,
        path="/",
        httponly=True,  # not readable by JavaScript, so XSS can't steal it
        samesite="lax",  # not sent on cross-site POSTs (CSRF defense)
        secure=settings.session_cookie_secure,
    )


async def _me(session: AsyncSession, user: User) -> MeResponse:
    memberships = await list_active_memberships(session, user.id)
    return MeResponse(
        user=UserOut(id=user.id, email=user.email, full_name=user.full_name),
        memberships=[
            MembershipOut(
                organization_id=organization.id,
                organization_name=organization.name,
                role=membership.role,
            )
            for membership, organization in memberships
        ],
    )


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest, session: SessionDep, settings: SettingsDep, response: Response
) -> MeResponse:
    user, issued = await service.register(
        session,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        organization_name=body.organization_name,
        session_ttl=_session_ttl(settings),
    )
    _set_session_cookie(response, issued, settings)
    return await _me(session, user)


@router.post("/login")
async def login(
    body: LoginRequest, session: SessionDep, settings: SettingsDep, response: Response
) -> MeResponse:
    try:
        user, issued = await service.login(
            session, email=body.email, password=body.password, session_ttl=_session_ttl(settings)
        )
    except service.InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS_DETAIL
        ) from None
    _set_session_cookie(response, issued, settings)
    return await _me(session, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    session: SessionDep, settings: SettingsDep, response: Response, token: SessionTokenDep = None
) -> None:
    if token:
        await service.logout(session, token)
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )


@router.get("/me")
async def me(user: CurrentUserDep, session: SessionDep) -> MeResponse:
    return await _me(session, user)
