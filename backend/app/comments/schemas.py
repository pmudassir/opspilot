import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel

from app.comments.models import COMMENT_BODY_MAX_LENGTH
from app.comments.service import CommentRow
from app.requests.schemas import PersonOut
from app.schemas import StrictRequest, trimmed_str


class CreateCommentBody(StrictRequest):
    body: trimmed_str(COMMENT_BODY_MAX_LENGTH)  # type: ignore[valid-type]


class CommentOut(BaseModel):
    id: uuid.UUID
    body: str
    author: PersonOut
    created_at: datetime

    @classmethod
    def from_row(cls, row: CommentRow) -> Self:
        comment = row.comment
        return cls(
            id=comment.id,
            body=comment.body,
            author=PersonOut(membership_id=comment.author_membership_id, full_name=row.author_name),
            created_at=comment.created_at,
        )
