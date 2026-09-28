import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.base import Base, UUIDPrimaryKeyMixin

COMMENT_BODY_MAX_LENGTH = 5000


class Comment(UUIDPrimaryKeyMixin, Base):
    """A comment on a request. Immutable in V1 (no edit/delete)."""

    __tablename__ = "comments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "request_id"],
            ["requests.organization_id", "requests.id"],
            name="fk_comments_request",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "author_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            name="fk_comments_author",
            ondelete="RESTRICT",
        ),
        # A request's comments, in order.
        Index("ix_comments_org_request_created", "organization_id", "request_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    request_id: Mapped[uuid.UUID]
    author_membership_id: Mapped[uuid.UUID]
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
