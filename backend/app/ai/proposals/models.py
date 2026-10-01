import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.base import Base, UUIDPrimaryKeyMixin, str_enum_column_type
from app.requests.models import RequestPriority, RequestStatus


class ProposalAction(StrEnum):
    ASSIGN = "assign"
    UNASSIGN = "unassign"
    CANCEL = "cancel"
    CHANGE_PRIORITY = "change_priority"
    COMMENT = "comment"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    EXECUTED = "executed"  # approved, and every item applied (one transaction)
    FAILED = "failed"  # approved, but nothing applied (stale, forbidden, conflict)
    REJECTED = "rejected"
    EXPIRED = "expired"


class AIProposal(UUIDPrimaryKeyMixin, Base):
    """An exact change the assistant proposed, waiting for its proposer's approval.
    Immutable apart from its outcome: changing anything means a new proposal."""

    __tablename__ = "ai_proposals"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),  # composite FK target (items)
        ForeignKeyConstraint(
            ["organization_id", "proposer_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            name="fk_ai_proposals_proposer",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "new_assignee_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            name="fk_ai_proposals_new_assignee",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "decided_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            name="fk_ai_proposals_decided_by",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["ai_usage.organization_id", "ai_usage.id"],
            name="fk_ai_proposals_run",
            ondelete="RESTRICT",
        ),
        # Each action carries exactly the parameter it needs.
        CheckConstraint("(action = 'assign') = (new_assignee_membership_id IS NOT NULL)", name="assign_has_assignee"),
        CheckConstraint("(action = 'change_priority') = (new_priority IS NOT NULL)", name="priority_has_priority"),
        CheckConstraint("(action = 'comment') = (comment_body IS NOT NULL)", name="comment_has_body"),
        # A person decided (approve/reject) exactly when the outcome isn't pending/expired.
        CheckConstraint(
            "(status IN ('pending', 'expired')) = (decided_by_membership_id IS NULL AND decided_at IS NULL)",
            name="decided_matches_status",
        ),
        CheckConstraint("(status = 'failed') = (failure_code IS NOT NULL)", name="failure_matches_status"),
        # "My proposals", newest first.
        Index("ix_ai_proposals_org_proposer_created", "organization_id", "proposer_membership_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"))
    proposer_membership_id: Mapped[uuid.UUID]
    run_id: Mapped[uuid.UUID | None]
    action: Mapped[ProposalAction] = mapped_column(str_enum_column_type(ProposalAction, name="ai_proposal_action"))
    new_assignee_membership_id: Mapped[uuid.UUID | None]
    new_priority: Mapped[RequestPriority | None] = mapped_column(
        str_enum_column_type(RequestPriority, name="ai_proposal_priority")
    )
    comment_body: Mapped[str | None] = mapped_column(Text)
    # SHA-256 of the canonical (action, parameters, items + versions): what the person saw.
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[ProposalStatus] = mapped_column(
        str_enum_column_type(ProposalStatus, name="ai_proposal_status"), default=ProposalStatus.PENDING
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by_membership_id: Mapped[uuid.UUID | None]
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(32))
    failure_detail: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIProposalItem(Base):
    """One request a proposal changes, and how it looked in the preview."""

    __tablename__ = "ai_proposal_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "proposal_id"],
            ["ai_proposals.organization_id", "ai_proposals.id"],
            name="fk_ai_proposal_items_proposal",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "request_id"],
            ["requests.organization_id", "requests.id"],
            name="fk_ai_proposal_items_request",
            ondelete="RESTRICT",
        ),
    )

    proposal_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"))
    position: Mapped[int] = mapped_column(SmallInteger)
    # The version the person saw: approval fails if the request changed since.
    expected_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Preview snapshot (what it looked like, not what it looks like now).
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[RequestStatus] = mapped_column(str_enum_column_type(RequestStatus, name="ai_proposal_item_status"))
    priority: Mapped[RequestPriority] = mapped_column(
        str_enum_column_type(RequestPriority, name="ai_proposal_item_priority")
    )
    assignee_name: Mapped[str | None] = mapped_column(String(200))
