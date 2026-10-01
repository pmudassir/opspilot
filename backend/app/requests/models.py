import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column_type

REQUEST_TITLE_MAX_LENGTH = 200
REQUEST_DESCRIPTION_MAX_LENGTH = 5000


class RequestStatus(StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RequestPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class RequestEventType(StrEnum):
    CREATED = "created"
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    STATUS_CHANGED = "status_changed"
    PRIORITY_CHANGED = "priority_changed"


class Request(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An operational request: the unit of work in V1 (ADR-001)."""

    __tablename__ = "requests"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),  # composite FK target (events, comments)
        ForeignKeyConstraint(
            ["organization_id", "department_id"],
            ["departments.organization_id", "departments.id"],
            name="fk_requests_department",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "requester_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            name="fk_requests_requester",
            ondelete="RESTRICT",
        ),
        # Nullable columns in a composite FK: the FK is only checked when assignee is set.
        ForeignKeyConstraint(
            ["organization_id", "assignee_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            name="fk_requests_assignee",
            ondelete="RESTRICT",
        ),
        # OPEN ⇔ no assignee; ASSIGNED/IN_PROGRESS/COMPLETED ⇒ assignee; CANCELLED ⇒ either.
        CheckConstraint(
            "(status = 'open' AND assignee_membership_id IS NULL)"
            " OR (status IN ('assigned', 'in_progress', 'completed')"
            " AND assignee_membership_id IS NOT NULL)"
            " OR status = 'cancelled'",
            name="status_matches_assignee",
        ),
        # Lifecycle timestamps must agree with the status they describe.
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)", name="completed_at_matches_status"
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)", name="cancelled_at_matches_status"
        ),
        CheckConstraint(
            "status <> 'in_progress' OR started_at IS NOT NULL", name="in_progress_has_started_at"
        ),
        # Default listing: newest first within an org, keyset-paginated on (created_at, id).
        Index("ix_requests_org_created", "organization_id", text("created_at DESC"), text("id DESC")),
        # A member's own requests (members can only see these).
        Index(
            "ix_requests_org_requester_created",
            "organization_id",
            "requester_membership_id",
            text("created_at DESC"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    department_id: Mapped[uuid.UUID]
    requester_membership_id: Mapped[uuid.UUID]
    assignee_membership_id: Mapped[uuid.UUID | None]
    title: Mapped[str] = mapped_column(String(REQUEST_TITLE_MAX_LENGTH))
    description: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[RequestStatus] = mapped_column(
        str_enum_column_type(RequestStatus, name="request_status"),
        default=RequestStatus.OPEN,
        server_default=RequestStatus.OPEN.value,
    )
    priority: Mapped[RequestPriority] = mapped_column(
        str_enum_column_type(RequestPriority, name="request_priority"),
        default=RequestPriority.NORMAL,
        server_default=RequestPriority.NORMAL.value,
    )
    # Lifecycle timestamps for metrics. assigned_at/started_at record the *first*
    # assignment/start (response-time metrics); the event log holds every change.
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RequestEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only history of a request (a DB trigger rejects UPDATE/DELETE).

    Status transitions get typed columns because metrics query them; anything else
    goes in `data`, an immutable snapshot that is displayed, never joined on.
    """

    __tablename__ = "request_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "request_id"],
            ["requests.organization_id", "requests.id"],
            name="fk_request_events_request",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            name="fk_request_events_actor",
            ondelete="RESTRICT",
        ),
        # A request's timeline, in order.
        Index("ix_request_events_org_request_created", "organization_id", "request_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    request_id: Mapped[uuid.UUID]
    actor_membership_id: Mapped[uuid.UUID]
    event_type: Mapped[RequestEventType] = mapped_column(
        str_enum_column_type(RequestEventType, name="request_event_type")
    )
    from_status: Mapped[RequestStatus | None] = mapped_column(
        str_enum_column_type(RequestStatus, name="request_event_from_status")
    )
    to_status: Mapped[RequestStatus | None] = mapped_column(
        str_enum_column_type(RequestStatus, name="request_event_to_status")
    )
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    # clock_timestamp(), not now(): now() is the *transaction* start time, so several
    # events written in one transaction would tie and the timeline order would be random.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
