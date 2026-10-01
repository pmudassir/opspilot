import uuid
from datetime import datetime
from typing import Annotated, Any, Self

from pydantic import BaseModel, StringConstraints

from app.requests.lifecycle import RequestAction
from app.requests.models import (
    REQUEST_DESCRIPTION_MAX_LENGTH,
    REQUEST_TITLE_MAX_LENGTH,
    RequestEventType,
    RequestPriority,
    RequestStatus,
)
from app.requests.service import EventRow, RequestRow
from app.schemas import StrictRequest, trimmed_str


class CreateRequestBody(StrictRequest):
    title: trimmed_str(REQUEST_TITLE_MAX_LENGTH)  # type: ignore[valid-type]
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=REQUEST_DESCRIPTION_MAX_LENGTH)
    ] = ""
    department_id: uuid.UUID
    priority: RequestPriority = RequestPriority.NORMAL


class AssignBody(StrictRequest):
    assignee_membership_id: uuid.UUID


class ChangePriorityBody(StrictRequest):
    priority: RequestPriority


class PersonOut(BaseModel):
    membership_id: uuid.UUID
    full_name: str


class DepartmentRef(BaseModel):
    id: uuid.UUID
    name: str


class RequestOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    status: RequestStatus
    priority: RequestPriority
    department: DepartmentRef
    requester: PersonOut
    assignee: PersonOut | None
    created_at: datetime
    updated_at: datetime
    assigned_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    # What the *current caller* may do now, computed by the same rules that enforce
    # each action. The UI renders buttons from this; the API still checks every call.
    allowed_actions: list[RequestAction]

    @classmethod
    def from_row(cls, row: RequestRow, allowed_actions: list[RequestAction]) -> Self:
        request = row.request
        assignee = (
            PersonOut(membership_id=request.assignee_membership_id, full_name=row.assignee_name)
            if request.assignee_membership_id is not None and row.assignee_name is not None
            else None
        )
        return cls(
            id=request.id,
            title=request.title,
            description=request.description,
            status=request.status,
            priority=request.priority,
            department=DepartmentRef(id=request.department_id, name=row.department_name),
            requester=PersonOut(
                membership_id=request.requester_membership_id, full_name=row.requester_name
            ),
            assignee=assignee,
            created_at=request.created_at,
            updated_at=request.updated_at,
            assigned_at=request.assigned_at,
            started_at=request.started_at,
            completed_at=request.completed_at,
            cancelled_at=request.cancelled_at,
            allowed_actions=allowed_actions,
        )


class RequestPage(BaseModel):
    items: list[RequestOut]
    next_cursor: str | None


class RequestEventOut(BaseModel):
    id: uuid.UUID
    event_type: RequestEventType
    from_status: RequestStatus | None
    to_status: RequestStatus | None
    actor: PersonOut
    data: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_row(cls, row: EventRow) -> Self:
        event = row.event
        return cls(
            id=event.id,
            event_type=event.event_type,
            from_status=event.from_status,
            to_status=event.to_status,
            actor=PersonOut(membership_id=event.actor_membership_id, full_name=row.actor_name),
            data=event.data,
            created_at=event.created_at,
        )
