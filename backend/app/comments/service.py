import uuid
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.comments.models import Comment
from app.organizations.models import Membership
from app.requests.service import Viewer, get_request
from app.users.models import User


class CommentRow(NamedTuple):
    comment: Comment
    author_name: str


async def add_comment(
    session: AsyncSession,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    *,
    author: Membership,
    viewer: Viewer,
    body: str,
) -> CommentRow:
    """Anyone who can see the request can comment on it (404 otherwise)."""
    await get_request(session, organization_id, request_id, viewer)
    comment = Comment(
        organization_id=organization_id,
        request_id=request_id,
        author_membership_id=author.id,
        body=body,
    )
    session.add(comment)
    await session.commit()
    author_name = await session.scalar(select(User.full_name).where(User.id == author.user_id))
    assert author_name is not None
    return CommentRow(comment, author_name)


async def list_comments(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, viewer: Viewer
) -> list[CommentRow]:
    await get_request(session, organization_id, request_id, viewer)
    result = await session.execute(
        select(Comment, User.full_name)
        .join(
            Membership,
            (Membership.organization_id == Comment.organization_id)
            & (Membership.id == Comment.author_membership_id),
        )
        .join(User, User.id == Membership.user_id)
        .where(Comment.organization_id == organization_id, Comment.request_id == request_id)
        .order_by(Comment.created_at, Comment.id)
    )
    return [CommentRow(*row) for row in result]
