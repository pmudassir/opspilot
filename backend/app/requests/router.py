import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.db import SessionDep
from app.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    decode_cursor,
    encode_cursor,
)
from app.permissions import Permission, has_permission
from app.requests import service
from app.requests.models import RequestPriority, RequestStatus
from app.requests.schemas import (
    CreateRequestBody,
    RequestEventOut,
    RequestOut,
    RequestPage,
)
from app.tenancy import TenantContext, authorized

router = APIRouter(prefix="/api/v1/orgs/{org_id}/requests", tags=["requests"])

RequestReader = authorized(Permission.REQUESTS_READ)


def _viewer(context: TenantContext) -> service.Viewer:
    return service.Viewer(
        membership_id=context.membership.id,
        can_read_all=has_permission(context.membership.role, Permission.REQUESTS_READ_ALL),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_request(
    body: CreateRequestBody,
    context: authorized(Permission.REQUESTS_CREATE),  # type: ignore[valid-type]
    session: SessionDep,
) -> RequestOut:
    row = await service.create_request(
        session,
        context.organization_id,
        requester_membership_id=context.membership.id,
        department_id=body.department_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
    )
    return RequestOut.from_row(row)


@router.get("")
async def list_requests(
    context: RequestReader,  # type: ignore[valid-type]
    session: SessionDep,
    status_filter: Annotated[list[RequestStatus] | None, Query(alias="status")] = None,
    department_id: uuid.UUID | None = None,
    priority: RequestPriority | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> RequestPage:
    rows, next_cursor = await service.list_requests(
        session,
        context.organization_id,
        _viewer(context),
        statuses=status_filter,
        department_id=department_id,
        priority=priority,
        limit=limit,
        after=decode_cursor(cursor) if cursor else None,
    )
    return RequestPage(
        items=[RequestOut.from_row(row) for row in rows],
        next_cursor=encode_cursor(next_cursor) if next_cursor else None,
    )


@router.get("/{request_id}")
async def get_request(
    request_id: uuid.UUID,
    context: RequestReader,  # type: ignore[valid-type]
    session: SessionDep,
) -> RequestOut:
    row = await service.get_request(session, context.organization_id, request_id, _viewer(context))
    return RequestOut.from_row(row)


@router.get("/{request_id}/events")
async def list_request_events(
    request_id: uuid.UUID,
    context: RequestReader,  # type: ignore[valid-type]
    session: SessionDep,
) -> list[RequestEventOut]:
    rows = await service.list_events(session, context.organization_id, request_id, _viewer(context))
    return [RequestEventOut.from_row(row) for row in rows]
