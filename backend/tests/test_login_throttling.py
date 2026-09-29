from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import LoginAttempt
from app.auth.throttling import PER_EMAIL, PER_EMAIL_AND_IP, PER_IP, WINDOW
from tests.helpers import DEFAULT_PASSWORD, login, signup

ClientFactory = Callable[..., AsyncClient]
WRONG = "definitely-wrong-password"


async def fail(client: AsyncClient, email: str, times: int) -> None:
    for _ in range(times):
        assert (await login(client, email=email, password=WRONG)).status_code == 401


@pytest.fixture
async def alice(make_client: ClientFactory) -> str:
    await signup(make_client(), email="alice@example.com")
    return "alice@example.com"


async def test_locks_email_ip_pair_after_limit_even_with_correct_password(
    make_client: ClientFactory, alice: str
) -> None:
    client = make_client("10.0.0.1")
    await fail(client, alice, PER_EMAIL_AND_IP.limit)

    response = await login(client, email=alice, password=DEFAULT_PASSWORD)

    assert response.status_code == 429
    retry_after = int(response.headers["Retry-After"])
    assert 0 < retry_after <= WINDOW.total_seconds()
    assert "Too many failed sign-in attempts" in response.json()["detail"]


async def test_other_addresses_can_still_sign_in(make_client: ClientFactory, alice: str) -> None:
    await fail(make_client("10.0.0.1"), alice, PER_EMAIL_AND_IP.limit)

    response = await login(make_client("10.0.0.2"), email=alice)

    assert response.status_code == 200


async def test_attempts_below_the_limit_are_not_blocked(make_client: ClientFactory, alice: str) -> None:
    client = make_client("10.0.0.1")
    await fail(client, alice, PER_EMAIL_AND_IP.limit - 1)

    assert (await login(client, email=alice)).status_code == 200


async def test_one_address_trying_many_accounts_is_blocked(make_client: ClientFactory) -> None:
    attacker = make_client("10.6.6.6")
    for n in range(PER_IP.limit):
        await fail(attacker, f"victim{n}@example.com", 1)

    response = await login(attacker, email="fresh-target@example.com", password=WRONG)

    assert response.status_code == 429


async def test_one_account_attacked_from_many_addresses_is_capped(
    make_client: ClientFactory, alice: str
) -> None:
    """Rotating (or spoofing) IPs doesn't allow unlimited guesses on one account."""
    for n in range(PER_EMAIL.limit):
        await fail(make_client(f"10.1.{n}.1"), alice, 1)

    response = await login(make_client("10.9.9.9"), email=alice)

    assert response.status_code == 429


async def test_unknown_emails_are_throttled_like_real_ones(make_client: ClientFactory) -> None:
    client = make_client("10.0.0.1")
    await fail(client, "nobody@example.com", PER_EMAIL_AND_IP.limit)

    assert (await login(client, email="nobody@example.com")).status_code == 429


async def test_throttled_attempts_are_not_recorded_or_hashed(
    make_client: ClientFactory, alice: str, db_session: AsyncSession
) -> None:
    client = make_client("10.0.0.1")
    await fail(client, alice, PER_EMAIL_AND_IP.limit)
    before = await db_session.scalar(select(func.count()).select_from(LoginAttempt))

    for _ in range(3):
        assert (await login(client, email=alice, password=WRONG)).status_code == 429

    assert await db_session.scalar(select(func.count()).select_from(LoginAttempt)) == before


async def test_block_lifts_when_failures_leave_the_window(
    make_client: ClientFactory, alice: str, db_session: AsyncSession
) -> None:
    client = make_client("10.0.0.1")
    await fail(client, alice, PER_EMAIL_AND_IP.limit)
    assert (await login(client, email=alice)).status_code == 429

    await db_session.execute(
        text("UPDATE login_attempts SET created_at = created_at - CAST(:age AS interval)"),
        {"age": WINDOW},
    )
    await db_session.commit()

    assert (await login(client, email=alice)).status_code == 200


async def test_successful_and_failed_attempts_are_recorded_with_ip(
    make_client: ClientFactory, alice: str, db_session: AsyncSession
) -> None:
    client = make_client("10.0.0.7")
    await fail(client, alice, 1)
    await login(client, email=alice)

    rows = (
        await db_session.execute(
            select(LoginAttempt.ip, LoginAttempt.succeeded).order_by(LoginAttempt.created_at)
        )
    ).all()
    assert [tuple(row) for row in rows] == [("10.0.0.7", False), ("10.0.0.7", True)]


async def test_login_removes_the_users_expired_sessions(
    make_client: ClientFactory, alice: str, db_session: AsyncSession
) -> None:
    await db_session.execute(text("UPDATE auth_sessions SET expires_at = now() - interval '1 day'"))
    await db_session.commit()

    await login(make_client(), email=alice)

    remaining = (await db_session.execute(text("SELECT expires_at > now() FROM auth_sessions"))).scalars().all()
    assert remaining == [True]  # only the fresh session
