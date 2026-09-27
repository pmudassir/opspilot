import asyncio
from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import SESSION_COOKIE_NAME
from app.auth.models import AuthSession
from app.auth.service import hash_session_token
from app.organizations.models import Membership, Organization
from app.users.models import User
from tests.helpers import DEFAULT_PASSWORD, login, session_cookie, signup

ME_URL = "/api/v1/auth/me"


@pytest.fixture
async def make_client(app: FastAPI) -> AsyncIterator[Callable[[], AsyncClient]]:
    """Independent clients = independent cookie jars = independent browsers."""
    clients: list[AsyncClient] = []

    def factory() -> AsyncClient:
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(c)
        return c

    yield factory
    for c in clients:
        await c.aclose()


# --- signup -----------------------------------------------------------------


async def test_signup_creates_user_org_admin_membership_and_logs_in(client: AsyncClient) -> None:
    response = await signup(client, email="alice@example.com", organization_name="Hotel A")

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "alice@example.com"
    assert [(m["organization_name"], m["role"]) for m in body["memberships"]] == [
        ("Hotel A", "admin")
    ]
    assert session_cookie(client) is not None
    assert (await client.get(ME_URL)).status_code == 200


async def test_signup_session_cookie_is_httponly_and_samesite_lax(client: AsyncClient) -> None:
    response = await signup(client)

    set_cookie = response.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE_NAME}=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


async def test_signup_normalizes_email_case_and_whitespace_in_names(client: AsyncClient) -> None:
    response = await signup(
        client, email="Alice@Example.COM", full_name="  Alice  ", organization_name=" Hotel A "
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["full_name"] == "Alice"
    assert body["memberships"][0]["organization_name"] == "Hotel A"


async def test_signup_never_returns_password_hash(client: AsyncClient) -> None:
    response = await signup(client)

    assert "password" not in response.text


async def test_signup_stores_argon2id_hash_not_plaintext(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await signup(client)

    stored_hash = await db_session.scalar(select(User.password_hash))
    assert stored_hash is not None
    assert stored_hash.startswith("$argon2id$")
    assert DEFAULT_PASSWORD not in stored_hash


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "not-an-email"),
        ("password", "short"),
        ("full_name", "   "),
        ("organization_name", ""),
    ],
)
async def test_signup_rejects_invalid_input(client: AsyncClient, field: str, value: str) -> None:
    payload = {
        "email": "alice@example.com",
        "password": DEFAULT_PASSWORD,
        "full_name": "Alice",
        "organization_name": "Hotel A",
        field: value,
    }

    response = await client.post("/api/v1/auth/signup", json=payload)

    assert response.status_code == 422


async def test_signup_rejects_unknown_fields(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "alice@example.com",
            "password": DEFAULT_PASSWORD,
            "full_name": "Alice",
            "organization_name": "Hotel A",
            "role": "admin",
        },
    )

    assert response.status_code == 422


async def test_duplicate_signup_is_409_and_leaves_no_partial_data(
    make_client: Callable[[], AsyncClient], db_session: AsyncSession
) -> None:
    await signup(make_client(), email="alice@example.com", organization_name="Hotel A")

    response = await signup(make_client(), email="ALICE@example.com", organization_name="Hotel B")

    assert response.status_code == 409
    # Atomicity: the failed signup must not leave "Hotel B" behind without an admin.
    assert await db_session.scalar(select(func.count()).select_from(Organization)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Membership)) == 1


async def test_concurrent_duplicate_signups_create_exactly_one_account(
    make_client: Callable[[], AsyncClient], db_session: AsyncSession
) -> None:
    responses = await asyncio.gather(
        signup(make_client(), email="alice@example.com", organization_name="Hotel A"),
        signup(make_client(), email="alice@example.com", organization_name="Hotel B"),
    )

    assert sorted(r.status_code for r in responses) == [201, 409]
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Organization)) == 1


# --- login ------------------------------------------------------------------


async def test_login_with_correct_credentials_returns_memberships(
    make_client: Callable[[], AsyncClient],
) -> None:
    await signup(make_client(), email="alice@example.com")
    client = make_client()

    response = await login(client, email="ALICE@example.com")

    assert response.status_code == 200
    assert response.json()["memberships"][0]["role"] == "admin"
    assert (await client.get(ME_URL)).json()["user"]["email"] == "alice@example.com"


async def test_login_failures_are_indistinguishable(
    make_client: Callable[[], AsyncClient],
) -> None:
    await signup(make_client(), email="alice@example.com")

    wrong_password = await login(make_client(), email="alice@example.com", password="wrong-pass")
    unknown_email = await login(make_client(), email="nobody@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert "set-cookie" not in wrong_password.headers
    assert "set-cookie" not in unknown_email.headers


# --- current user / sessions -------------------------------------------------


async def test_me_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get(ME_URL)).status_code == 401


async def test_me_rejects_forged_token(client: AsyncClient) -> None:
    client.cookies.set(SESSION_COOKIE_NAME, "made-up-token")

    assert (await client.get(ME_URL)).status_code == 401


async def test_session_token_is_stored_only_as_a_hash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await signup(client)
    token = session_cookie(client)
    assert token is not None

    stored = await db_session.scalar(select(AuthSession.token_hash))
    assert stored == hash_session_token(token)
    assert token.encode() not in stored


async def test_expired_session_is_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    await signup(client)
    await db_session.execute(text("UPDATE auth_sessions SET expires_at = now() - interval '1 second'"))
    await db_session.commit()

    assert (await client.get(ME_URL)).status_code == 401


async def test_logout_revokes_the_session_server_side(make_client: Callable[[], AsyncClient]) -> None:
    client = make_client()
    await signup(client)
    stolen_token = session_cookie(client)
    assert stolen_token is not None

    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert (await client.get(ME_URL)).status_code == 401
    # Clearing the browser cookie is not enough; a copied token must also stop working.
    attacker = make_client()
    attacker.cookies.set(SESSION_COOKIE_NAME, stolen_token)
    assert (await attacker.get(ME_URL)).status_code == 401


async def test_logout_without_a_session_is_a_noop(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/auth/logout")).status_code == 204


async def test_deactivated_memberships_are_not_listed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await signup(client)
    await db_session.execute(text("UPDATE memberships SET status = 'deactivated'"))
    await db_session.commit()

    assert (await client.get(ME_URL)).json()["memberships"] == []


# --- CSRF ---------------------------------------------------------------------


async def test_state_changing_request_from_foreign_origin_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.post(
        "/api/v1/auth/signup",
        headers={"Origin": "https://evil.example"},
        json={
            "email": "alice@example.com",
            "password": DEFAULT_PASSWORD,
            "full_name": "Alice",
            "organization_name": "Hotel A",
        },
    )

    assert response.status_code == 403
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


async def test_state_changing_request_from_allowed_origin_is_accepted(client: AsyncClient) -> None:
    client.headers["Origin"] = "http://localhost:3000"

    assert (await signup(client)).status_code == 201
