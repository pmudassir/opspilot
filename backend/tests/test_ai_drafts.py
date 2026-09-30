from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.dependencies import get_drafter
from app.ai.drafter import DrafterError, DraftFailure, ModelDraft, TokenUsage
from app.ai.models import AIUsage
from app.config import get_settings
from app.db import engine
from app.requests.models import Request, RequestPriority
from tests.helpers import (
    add_member_id,
    create_department_id,
    logged_in,
    org_url,
    signup_org,
)

TEXT = "The Wi-Fi in the second-floor meeting room keeps disconnecting; client meeting in 20 minutes."


def suggestion(department: str | None = "IT", **overrides: object) -> ModelDraft:
    values: dict = dict(
        title="Wi-Fi drops in second-floor meeting room",
        description="Keeps disconnecting; client meeting in 20 minutes.",
        department=department,
        priority=RequestPriority.URGENT,
        rationale="Network issue with imminent business impact.",
        usage=TokenUsage(input_tokens=412, output_tokens=96),
    )
    values.update(overrides)
    return ModelDraft(**values)


@dataclass
class FakeDrafter:
    result: ModelDraft | None = None
    error: DrafterError | None = None
    provider: str = "fake"
    model: str = "fake-model-1"
    calls: list[tuple[str, list[str]]] = field(default_factory=list)
    during_call: Callable[[], Awaitable[None]] | None = None

    async def draft(self, *, text: str, departments: list[str]) -> ModelDraft:
        self.calls.append((text, departments))
        if self.during_call:
            await self.during_call()
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result


@pytest.fixture
def drafter(app: FastAPI) -> FakeDrafter:
    fake = FakeDrafter(result=suggestion())
    app.dependency_overrides[get_drafter] = lambda: fake
    return fake


@dataclass(frozen=True)
class Org:
    org_id: str
    admin: AsyncClient
    it: str


@pytest.fixture
async def org(make_client: Callable[..., AsyncClient]) -> Org:
    admin = make_client()
    org_id = await signup_org(admin, email="alice@a.example", organization_name="Hotel A")
    it = await create_department_id(admin, org_id, "IT")
    await create_department_id(admin, org_id, "Housekeeping")
    return Org(org_id, admin, it)


async def draft(client: AsyncClient, org_id: str, text: str = TEXT):  # noqa: ANN201
    return await client.post(org_url(org_id, "/ai/request-drafts"), json={"text": text})


async def test_draft_maps_the_suggested_department_name_to_this_orgs_id(
    org: Org, drafter: FakeDrafter
) -> None:
    drafter.result = suggestion(department="it")  # case differs: still this org's IT

    response = await draft(org.admin, org.org_id)

    assert response.status_code == 200
    body = response.json()
    assert (body["department_id"], body["department_name"]) == (org.it, "IT")
    assert body["priority"] == "urgent"
    assert body["rationale"] == "Network issue with imminent business impact."
    assert body["model"] == "fake-model-1"
    # The model saw this org's department names and the user's text, nothing else.
    assert drafter.calls == [(TEXT, ["Housekeeping", "IT"])]


@pytest.mark.parametrize("department", ["Legal", "", None])
async def test_unknown_or_missing_department_becomes_no_suggestion(
    org: Org, drafter: FakeDrafter, department: str | None
) -> None:
    drafter.result = suggestion(department=department)

    body = (await draft(org.admin, org.org_id)).json()

    assert (body["department_id"], body["department_name"]) == (None, None)


async def test_a_draft_is_only_a_suggestion_nothing_is_saved(
    org: Org, drafter: FakeDrafter, db_session: AsyncSession
) -> None:
    await draft(org.admin, org.org_id)

    assert await db_session.scalar(select(func.count()).select_from(Request)) == 0


async def test_successful_calls_are_recorded_for_cost_and_latency(
    org: Org, drafter: FakeDrafter, db_session: AsyncSession
) -> None:
    await draft(org.admin, org.org_id)

    usage = (await db_session.scalars(select(AIUsage))).one()
    assert (usage.outcome, usage.provider, usage.model) == ("success", "fake", "fake-model-1")
    assert (usage.input_tokens, usage.output_tokens) == (412, 96)
    assert usage.latency_ms >= 0
    assert usage.prompt_version.startswith("request-draft-")


async def test_no_database_transaction_is_held_open_during_the_provider_call(
    org: Org, drafter: FakeDrafter
) -> None:
    # A provider call can take many seconds; an open transaction would pin a pooled
    # connection ("idle in transaction") for all that time.
    idle_in_transaction: list[int] = []

    async def count_idle_transactions() -> None:
        async with engine.connect() as connection:
            idle_in_transaction.append(
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
                        " AND state = 'idle in transaction' AND pid <> pg_backend_pid()"
                    )
                )
            )

    drafter.during_call = count_idle_transactions
    assert (await draft(org.admin, org.org_id)).status_code == 200
    assert idle_in_transaction == [0]


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (DraftFailure.TIMEOUT, 504),
        (DraftFailure.RATE_LIMITED, 503),
        (DraftFailure.PROVIDER_ERROR, 502),
        (DraftFailure.INVALID_OUTPUT, 502),
    ],
)
async def test_provider_failures_are_reported_and_recorded(
    org: Org, drafter: FakeDrafter, db_session: AsyncSession, failure: DraftFailure, status: int
) -> None:
    drafter.error = DrafterError(failure, "boom", retry_after_seconds=7 if failure == DraftFailure.RATE_LIMITED else None)

    response = await draft(org.admin, org.org_id)

    assert response.status_code == status
    assert "fill in the request yourself" in response.json()["detail"]
    assert "boom" not in response.json()["detail"]  # internal detail isn't leaked
    if failure == DraftFailure.RATE_LIMITED:
        assert response.headers["Retry-After"] == "7"
    assert await db_session.scalar(select(AIUsage.outcome)) == failure.value


async def test_without_ai_configured_the_feature_is_off(
    org: Org, app: FastAPI, db_session: AsyncSession
) -> None:
    app.dependency_overrides[get_drafter] = lambda: None

    response = await draft(org.admin, org.org_id)
    me = (await org.admin.get("/api/v1/auth/me")).json()

    assert response.status_code == 503
    assert me["features"]["ai_request_drafts"] is False
    assert await db_session.scalar(select(func.count()).select_from(AIUsage)) == 0


async def test_me_reports_the_feature_when_configured(org: Org, drafter: FakeDrafter) -> None:
    me = (await org.admin.get("/api/v1/auth/me")).json()

    assert me["features"]["ai_request_drafts"] is True


async def test_per_member_quota_limits_spend(org: Org, drafter: FakeDrafter, app: FastAPI) -> None:
    limited = get_settings().model_copy(update={"ai_drafts_per_hour": 2})
    app.dependency_overrides[get_settings] = lambda: limited

    statuses = [(await draft(org.admin, org.org_id)).status_code for _ in range(3)]

    assert statuses == [200, 200, 429]
    assert len(drafter.calls) == 2  # the over-quota call never reached the provider


@pytest.mark.parametrize("text", ["too short", "x" * 2001])
async def test_input_length_is_bounded(org: Org, drafter: FakeDrafter, text: str) -> None:
    assert (await draft(org.admin, org.org_id, text)).status_code == 422
    assert drafter.calls == []


async def test_any_member_who_can_create_requests_can_draft(
    org: Org, drafter: FakeDrafter, make_client: Callable[..., AsyncClient]
) -> None:
    await add_member_id(org.admin, org.org_id, email="mia@a.example", role="member")
    mia = await logged_in(make_client(), "mia@a.example")

    assert (await draft(mia, org.org_id)).status_code == 200
