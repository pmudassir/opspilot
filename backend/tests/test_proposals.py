"""Human-in-the-loop approvals, without any model: proposals are drafted and stored by the
service, then approved/rejected over HTTP. Covers binding, staleness, expiry, who may
approve, all-or-nothing execution, and double-click / concurrent approvals."""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.proposals import service
from app.ai.proposals.models import AIProposal, ProposalAction, ProposalStatus
from app.ai.proposals.service import (
    NothingToProposeError,
    draft_proposal,
    expire_stale_proposals,
)
from app.comments.models import Comment
from app.organizations.models import Membership
from app.requests.models import Request, RequestEvent, RequestPriority
from tests.helpers import (
    act,
    add_member_id,
    create_department_id,
    create_request_id,
    logged_in,
    org_url,
    signup_org,
)


@dataclass(frozen=True)
class Org:
    org_id: str
    admin: AsyncClient
    clients: dict[str, AsyncClient]
    ids: dict[str, str]  # membership ids
    requests: list[str]  # three OPEN IT requests reported by Mia
    other_org: str
    other_admin: AsyncClient


@pytest.fixture
async def org(make_client: Callable[..., AsyncClient]) -> Org:
    admin = make_client()
    org_id = await signup_org(admin, email="alice@a.example", organization_name="Hotel A")
    roles = {"manager": "manager", "manager2": "manager", "agent": "agent", "mia": "member"}
    ids = {name: await add_member_id(admin, org_id, email=f"{name}@a.example", role=role) for name, role in roles.items()}
    it = await create_department_id(admin, org_id, "IT")
    for name in ("manager", "agent"):
        assert (await admin.put(org_url(org_id, f"/departments/{it}/members/{ids[name]}"))).status_code == 204
    clients = {name: await logged_in(make_client(), f"{name}@a.example") for name in roles}
    requests = [await create_request_id(clients["mia"], org_id, it, title=f"Request {n}") for n in range(3)]
    other_admin = make_client()
    other_org = await signup_org(other_admin, email="bob@b.example", organization_name="Hotel B")
    return Org(org_id, admin, clients, ids, requests, other_org, other_admin)


async def membership(db: AsyncSession, membership_id: str) -> Membership:
    found = await db.scalar(select(Membership).where(Membership.id == uuid.UUID(membership_id)))
    assert found is not None
    return found


async def propose(
    db: AsyncSession, org: Org, who: str, action: ProposalAction, request_ids: list[str] | None = None, **params: Any
) -> dict:
    """Draft + store a proposal the way the assistant does, then read it over HTTP."""
    proposer = await membership(db, org.ids[who])
    draft = await draft_proposal(
        db, uuid.UUID(org.org_id), proposer, action, [uuid.UUID(r) for r in request_ids or org.requests], **params
    )
    proposal = await service.create_proposal(
        db, organization_id=uuid.UUID(org.org_id), proposer_membership_id=proposer.id, run_id=None, draft=draft
    )
    await db.commit()
    response = await org.clients[who].get(org_url(org.org_id, f"/ai/proposals/{proposal.id}"))
    assert response.status_code == 200, response.text
    return response.json()


async def approve(org: Org, who: str, proposal: dict, payload_hash: str | None = None) -> Response:
    url = org_url(org.org_id, f"/ai/proposals/{proposal['id']}/approve")
    return await org.clients[who].post(url, json={"payload_hash": payload_hash or proposal["payload_hash"]})


async def reject(org: Org, who: str, proposal: dict) -> Response:
    return await org.clients[who].post(org_url(org.org_id, f"/ai/proposals/{proposal['id']}/reject"))


async def request_states(db: AsyncSession, org: Org) -> list[tuple[str, str]]:
    db.expire_all()
    rows = await db.execute(
        select(Request.title, Request.status).where(Request.id.in_([uuid.UUID(r) for r in org.requests])).order_by(Request.title)
    )
    return [(title, status.value) for title, status in rows]


async def approval_events(db: AsyncSession, proposal: dict) -> int:
    return await db.scalar(
        select(func.count()).select_from(RequestEvent).where(RequestEvent.data["approval_id"].astext == proposal["id"])
    ) or 0


# --- drafting -----------------------------------------------------------------


async def test_a_proposal_is_an_exact_preview_and_changes_nothing(db_session: AsyncSession, org: Org) -> None:
    proposal = await propose(db_session, org, "manager", ProposalAction.CANCEL)
    assert proposal["status"] == "pending" and proposal["summary"] == "Cancel 3 requests"
    assert [i["title"] for i in proposal["items"]] == ["Request 0", "Request 1", "Request 2"]
    assert all(i["status"] == "open" for i in proposal["items"])
    assert len(proposal["payload_hash"]) == 64
    assert await request_states(db_session, org) == [(f"Request {n}", "open") for n in range(3)]


async def test_drafting_is_read_only(db_session: AsyncSession, org: Org) -> None:
    proposer = await membership(db_session, org.ids["manager"])
    await db_session.commit()
    async with db_session.begin():
        await db_session.execute(text("SET TRANSACTION READ ONLY"))  # would fail on any write
        draft = await draft_proposal(db_session, uuid.UUID(org.org_id), proposer, ProposalAction.CANCEL, [uuid.UUID(r) for r in org.requests])
    assert len(draft.items) == 3


async def test_requests_the_proposer_cant_change_are_excluded_with_reasons(db_session: AsyncSession, org: Org) -> None:
    await act(org.admin, org.org_id, org.requests[0], "assign", {"assignee_membership_id": org.ids["agent"]})
    proposer = await membership(db_session, org.ids["mia"])
    # Mia may cancel her own requests only while they're open.
    draft = await draft_proposal(db_session, uuid.UUID(org.org_id), proposer, ProposalAction.CANCEL, [uuid.UUID(r) for r in org.requests])
    assert [i.title for i in draft.items] == ["Request 1", "Request 2"]
    assert [e.title for e in draft.excluded] == ["Request 0"] and "open" in draft.excluded[0].reason


async def test_nothing_to_propose(db_session: AsyncSession, org: Org) -> None:
    proposer = await membership(db_session, org.ids["agent"])  # agents can't cancel others' requests
    with pytest.raises(NothingToProposeError):
        await draft_proposal(db_session, uuid.UUID(org.org_id), proposer, ProposalAction.CANCEL, [uuid.UUID(r) for r in org.requests])
    with pytest.raises(NothingToProposeError):
        await draft_proposal(db_session, uuid.UUID(org.org_id), proposer, ProposalAction.CANCEL, [uuid.uuid4()] * 0)
    with pytest.raises(NothingToProposeError):
        await draft_proposal(db_session, uuid.UUID(org.org_id), proposer, ProposalAction.COMMENT, [uuid.UUID(r) for r in org.requests], comment_body="x")


# --- approving ----------------------------------------------------------------


async def test_approve_executes_everything_and_records_who(db_session: AsyncSession, org: Org) -> None:
    proposal = await propose(db_session, org, "manager", ProposalAction.CANCEL)
    response = await approve(org, "manager", proposal)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "executed" and body["decided_at"] and body["failure_code"] is None
    assert await request_states(db_session, org) == [(f"Request {n}", "cancelled") for n in range(3)]
    assert await approval_events(db_session, proposal) == 3
    events = (await db_session.scalars(select(RequestEvent).where(RequestEvent.event_type == "status_changed"))).all()
    assert {str(e.actor_membership_id) for e in events} == {org.ids["manager"]}


@pytest.mark.parametrize(
    ("action", "params", "check"),
    [
        (ProposalAction.ASSIGN, {"assignee": "agent"}, "assigned"),
        (ProposalAction.CHANGE_PRIORITY, {"new_priority": RequestPriority.URGENT}, "urgent"),
    ],
)
async def test_approve_assign_and_priority(
    db_session: AsyncSession, org: Org, action: ProposalAction, params: dict, check: str
) -> None:
    if "assignee" in params:
        params = {"new_assignee_membership_id": uuid.UUID(org.ids[params.pop("assignee")])}
    proposal = await propose(db_session, org, "manager", action, org.requests[:2], **params)
    if action == ProposalAction.ASSIGN:
        assert proposal["summary"] == "Assign 2 requests to Agent" and proposal["new_assignee_name"] == "Agent"
    assert (await approve(org, "manager", proposal)).json()["status"] == "executed"
    db_session.expire_all()
    rows = (await db_session.scalars(select(Request).where(Request.id.in_([uuid.UUID(r) for r in org.requests[:2]])))).all()
    assert all(check in (r.status.value, r.priority.value) for r in rows)


async def test_approve_comment(db_session: AsyncSession, org: Org) -> None:
    proposal = await propose(db_session, org, "agent", ProposalAction.COMMENT, org.requests[:1], comment_body="Part ordered.")
    assert (await approve(org, "agent", proposal)).json()["status"] == "executed"
    comment = await db_session.scalar(select(Comment))
    assert comment is not None and comment.body == "Part ordered." and str(comment.author_membership_id) == org.ids["agent"]


async def test_approving_twice_executes_once(db_session: AsyncSession, org: Org) -> None:
    proposal = await propose(db_session, org, "manager", ProposalAction.CANCEL)
    first, second = await approve(org, "manager", proposal), await approve(org, "manager", proposal)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert await approval_events(db_session, proposal) == 3


@pytest.fixture
def slow_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold the first approval inside its transaction, so a second one arrives while it runs."""
    original = service.proposal_items

    async def slow(session: AsyncSession, proposal: AIProposal) -> list:
        items = await original(session, proposal)
        await asyncio.sleep(0.3)
        return items

    monkeypatch.setattr(service, "proposal_items", slow)


async def test_concurrent_approvals_execute_once(db_session: AsyncSession, org: Org, slow_execution: None) -> None:
    proposal = await propose(db_session, org, "manager", ProposalAction.CANCEL)
    responses = await asyncio.gather(approve(org, "manager", proposal), approve(org, "manager", proposal))
    assert [r.status_code for r in responses] == [200, 200]
    # The second waited on the row lock, then saw the outcome: it didn't run (and fail as stale).
    assert [r.json()["status"] for r in responses] == ["executed", "executed"]
    assert await approval_events(db_session, proposal) == 3


async def test_approve_racing_reject_has_one_outcome(db_session: AsyncSession, org: Org, slow_execution: None) -> None:
    proposal = await propose(db_session, org, "manager", ProposalAction.CANCEL)
    approved, rejected = await asyncio.gather(approve(org, "manager", proposal), reject(org, "manager", proposal))
    outcomes = {approved.status_code, rejected.status_code}
    assert outcomes == {200, 409}
    final = (await org.clients["manager"].get(org_url(org.org_id, f"/ai/proposals/{proposal['id']}"))).json()
    changed = await request_states(db_session, org) != [(f"Request {n}", "open") for n in range(3)]
    assert (final["status"] == "executed") == changed


# --- binding, staleness, expiry, authorization ----------------------------------


async def test_approval_binds_to_what_was_shown(db_session: AsyncSession, org: Org) -> None:
    proposal = await propose(db_session, org, "manager", ProposalAction.CANCEL)
    response = await approve(org, "manager", proposal, payload_hash="0" * 64)
    assert response.status_code == 409
    assert (await org.clients["manager"].get(org_url(org.org_id, f"/ai/proposals/{proposal['id']}"))).json()["status"] == "pending"


async def test_a_change_after_the_preview_fails_the_whole_approval(db_session: AsyncSession, org: Org) -> None:
    proposal = await propose(db_session, org, "manager", ProposalAction.CANCEL)
    # Someone works on one request after the preview was shown.
    await act(org.admin, org.org_id, org.requests[1], "assign", {"assignee_membership_id": org.ids["agent"]})
    body = (await approve(org, "manager", proposal)).json()
    assert body["status"] == "failed" and body["failure_code"] == "stale"
    # All or nothing: the other two weren't cancelled either.
    assert await request_states(db_session, org) == [("Request 0", "open"), ("Request 1", "assigned"), ("Request 2", "open")]
    assert await approval_events(db_session, proposal) == 0


async def test_losing_permission_before_approval_fails_it(db_session: AsyncSession, org: Org) -> None:
    proposal = await propose(db_session, org, "manager", ProposalAction.CANCEL)
    await org.admin.patch(org_url(org.org_id, f"/members/{org.ids['manager']}"), json={"role": "agent"})
    body = (await approve(org, "manager", proposal)).json()
    assert body["status"] == "failed" and body["failure_code"] == "forbidden"
    assert await request_states(db_session, org) == [(f"Request {n}", "open") for n in range(3)]


async def test_expired_proposals_cant_be_approved(db_session: AsyncSession, org: Org) -> None:
    proposal = await propose(db_session, org, "manager", ProposalAction.CANCEL)
    await db_session.execute(text("UPDATE ai_proposals SET expires_at = now() - interval '1 second'"))
    await db_session.commit()
    shown = (await org.clients["manager"].get(org_url(org.org_id, f"/ai/proposals/{proposal['id']}"))).json()
    assert shown["status"] == "expired"  # shown as expired before anything marks it
    response = await approve(org, "manager", proposal)
    assert response.status_code == 409 and "expired" in response.json()["detail"]
    assert await request_states(db_session, org) == [(f"Request {n}", "open") for n in range(3)]


async def test_maintenance_expires_stale_proposals(db_session: AsyncSession, org: Org) -> None:
    stale = await propose(db_session, org, "manager", ProposalAction.CANCEL)
    fresh = await propose(db_session, org, "manager", ProposalAction.CHANGE_PRIORITY, new_priority=RequestPriority.HIGH)
    await db_session.execute(
        text("UPDATE ai_proposals SET expires_at = now() - interval '1 second' WHERE id = :id"), {"id": stale["id"]}
    )
    await db_session.commit()
    assert await expire_stale_proposals(db_session) == 1
    assert await expire_stale_proposals(db_session) == 0  # idempotent
    statuses = dict((await db_session.execute(select(AIProposal.id, AIProposal.status))).all())
    assert statuses == {uuid.UUID(stale["id"]): ProposalStatus.EXPIRED, uuid.UUID(fresh["id"]): ProposalStatus.PENDING}


@pytest.mark.parametrize("who", ["manager2", "agent", "mia"])
async def test_only_the_proposer_can_see_or_decide(db_session: AsyncSession, org: Org, who: str) -> None:
    proposal = await propose(db_session, org, "manager", ProposalAction.CANCEL)
    assert (await org.clients[who].get(org_url(org.org_id, f"/ai/proposals/{proposal['id']}"))).status_code == 404
    assert (await approve(org, who, proposal)).status_code == 404
    assert (await reject(org, who, proposal)).status_code == 404


async def test_reject(db_session: AsyncSession, org: Org) -> None:
    proposal = await propose(db_session, org, "manager", ProposalAction.CANCEL)
    first, again = await reject(org, "manager", proposal), await reject(org, "manager", proposal)
    assert first.json()["status"] == again.json()["status"] == "rejected"
    assert (await approve(org, "manager", proposal)).status_code == 409
    assert await request_states(db_session, org) == [(f"Request {n}", "open") for n in range(3)]
