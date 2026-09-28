import uuid

from fastapi import APIRouter, status

from app.comments import service
from app.comments.schemas import CommentOut, CreateCommentBody
from app.db import SessionDep
from app.permissions import Permission
from app.requests.service import viewer_for
from app.tenancy import authorized

router = APIRouter(
    prefix="/api/v1/orgs/{org_id}/requests/{request_id}/comments", tags=["comments"]
)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_comment(
    request_id: uuid.UUID,
    body: CreateCommentBody,
    context: authorized(Permission.REQUESTS_COMMENT),  # type: ignore[valid-type]
    session: SessionDep,
) -> CommentOut:
    row = await service.add_comment(
        session,
        context.organization_id,
        request_id,
        author=context.membership,
        viewer=viewer_for(context.membership),
        body=body.body,
    )
    return CommentOut.from_row(row)


@router.get("")
async def list_comments(
    request_id: uuid.UUID,
    context: authorized(Permission.REQUESTS_READ),  # type: ignore[valid-type]
    session: SessionDep,
) -> list[CommentOut]:
    rows = await service.list_comments(
        session, context.organization_id, request_id, viewer_for(context.membership)
    )
    return [CommentOut.from_row(row) for row in rows]
