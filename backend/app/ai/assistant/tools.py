"""Read-only tools the assistant model may ask for.

Each tool is a thin adapter over an existing service function, so it gets the same
queries, tenant scoping and visibility rules as the REST API. Arguments are validated
like any user input, and none of them can name an organization, a user or a database
id: the organization and the acting membership come from the server (ToolEnv).
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.assistant.refs import RefRegistry
from app.comments.service import list_comments
from app.departments.models import DEPARTMENT_NAME_MAX_LENGTH
from app.departments.service import list_department_staff, list_departments
from app.errors import NotFoundError
from app.metrics.service import DepartmentMetrics, organization_metrics
from app.organizations.models import Membership, MembershipRole
from app.permissions import Permission, has_permission
from app.requests.lifecycle import allowed_actions, load_actor
from app.requests.models import RequestPriority, RequestStatus
from app.requests.service import (
    RequestFilters,
    RequestRow,
    count_requests,
    get_request,
    list_events,
    list_requests,
    viewer_for,
)
from app.users.models import User

DESCRIPTION_MAX_CHARS = 1000
COMMENT_MAX_CHARS = 200
HISTORY_MAX_ITEMS = 20


class ToolErrorCode(StrEnum):
    INVALID_ARGUMENTS = "invalid_arguments"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    AMBIGUOUS = "ambiguous"


class ToolError(Exception):
    """An expected failure, reported back to the model so it can correct itself.
    Messages are safe to show: they never contain ids or other tenants' data."""

    def __init__(self, code: ToolErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ToolEnv:
    """Everything a tool may act with. Built by the executor from the server's view of
    the caller (fresh membership, database clock), never from model output."""

    session: AsyncSession
    organization_id: uuid.UUID
    membership: Membership
    now: datetime
    refs: RefRegistry


@dataclass(frozen=True)
class ToolResult:
    data: dict[str, Any]
    count: int | None = None  # rows returned, for the audit log


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


DepartmentName = Annotated[str, Field(min_length=1, max_length=DEPARTMENT_NAME_MAX_LENGTH)]
Ref = Annotated[
    str,
    Field(pattern=r"^[Rr][0-9]{1,3}$", description="A request ref such as R1, from an earlier result"),
]


ACTIVE_STATUSES = [RequestStatus.OPEN, RequestStatus.ASSIGNED, RequestStatus.IN_PROGRESS]


class SearchRequestsArgs(_Args):
    status: list[RequestStatus] | None = Field(
        None, max_length=len(RequestStatus), description="Omit for active requests (open, assigned, in progress)"
    )
    department: DepartmentName | None = None
    priority: list[RequestPriority] | None = Field(None, max_length=len(RequestPriority))
    assignee: str | None = Field(
        None, min_length=1, max_length=100, description='"me" or a person\'s full name'
    )
    unassigned: bool = Field(False, description="Only requests nobody is assigned to")
    requested_by_me: bool = False
    title_contains: str | None = Field(None, min_length=1, max_length=100)
    created_within_days: int | None = Field(None, ge=1, le=90)
    limit: int = Field(10, ge=1, le=20)


class RequestRefArgs(_Args):
    ref: Ref


class NoArgs(_Args):
    pass


class DepartmentArgs(_Args):
    department: DepartmentName


class DepartmentStatusArgs(_Args):
    department: DepartmentName | None = Field(None, description="Omit to compare every department")
    period_days: int = Field(7, ge=1, le=90)


# --- helpers ------------------------------------------------------------------


def _minutes(value: datetime | None) -> str | None:
    return value.isoformat(timespec="minutes") if value else None


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _summary(env: ToolEnv, row: RequestRow) -> dict[str, Any]:
    request = row.request
    return {
        "ref": env.refs.ref_for(request.id),
        "title": request.title,
        "status": request.status,
        "priority": request.priority,
        "department": row.department_name,
        "assignee": row.assignee_name,
        "requester": row.requester_name,
        "age_hours": round((env.now - request.created_at).total_seconds() / 3600, 1),
    }


async def _department_id(env: ToolEnv, name: str) -> uuid.UUID:
    """Exact, case-insensitive match among THIS organization's departments only."""
    departments = await list_departments(env.session, env.organization_id)
    match = next((d for d in departments if d.name.casefold() == name.casefold()), None)
    if match is None:
        names = ", ".join(d.name for d in departments) or "none"
        raise ToolError(ToolErrorCode.INVALID_ARGUMENTS, f"No department named {name!r}. Departments: {names}.")
    return match.id


async def _person_membership_id(env: ToolEnv, name: str) -> uuid.UUID:
    # Looking people up by name reveals who is in the organization: same rule as the members list.
    if not has_permission(env.membership.role, Permission.MEMBERS_READ):
        raise ToolError(ToolErrorCode.FORBIDDEN, 'Your role can\'t look up other people; use "me" or "unassigned".')
    ids = list(
        await env.session.scalars(
            select(Membership.id)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == env.organization_id, func.lower(User.full_name) == name.lower())
        )
    )
    if not ids:
        raise ToolError(ToolErrorCode.INVALID_ARGUMENTS, f"No one named {name!r} in this organization.")
    if len(ids) > 1:
        raise ToolError(ToolErrorCode.AMBIGUOUS, f"{len(ids)} people are named {name!r}; ask the user which one.")
    return ids[0]


async def _load(env: ToolEnv, ref: str) -> RequestRow:
    request_id = env.refs.resolve(ref)
    if request_id is None:
        raise ToolError(
            ToolErrorCode.NOT_FOUND,
            f"Unknown ref {ref}. Only refs from earlier results can be used; find requests with search_requests.",
        )
    try:
        # Re-checked on every use: a ref is a pointer, never a permission.
        return await get_request(env.session, env.organization_id, request_id, viewer_for(env.membership))
    except NotFoundError:
        raise ToolError(ToolErrorCode.NOT_FOUND, f"{ref} doesn't exist or isn't visible to you.") from None


# --- tools --------------------------------------------------------------------


async def search_requests(env: ToolEnv, args: SearchRequestsArgs) -> ToolResult:
    if args.unassigned and args.assignee and args.assignee.casefold() != "unassigned":
        raise ToolError(ToolErrorCode.INVALID_ARGUMENTS, "Use either assignee or unassigned, not both.")
    assignee_id: uuid.UUID | None = None
    unassigned = args.unassigned
    if args.assignee is not None:
        match args.assignee.casefold():
            case "me":
                assignee_id = env.membership.id
            case "unassigned":  # tolerated: models sometimes put it here instead of the flag
                unassigned = True
            case _:
                assignee_id = await _person_membership_id(env, args.assignee)
    filters = RequestFilters(
        # "Which requests are unassigned?" means active ones: closed requests only when asked for.
        statuses=args.status or ACTIVE_STATUSES,
        department_id=await _department_id(env, args.department) if args.department else None,
        priorities=args.priority,
        assignee_membership_id=assignee_id,
        unassigned=unassigned,
        requester_membership_id=env.membership.id if args.requested_by_me else None,
        title_contains=args.title_contains,
        created_within=timedelta(days=args.created_within_days) if args.created_within_days else None,
    )
    viewer = viewer_for(env.membership)
    rows, _ = await list_requests(env.session, env.organization_id, viewer, filters, limit=args.limit, after=None)
    # The total tells the model (and so the user) when it is only seeing some of the matches.
    total = await count_requests(env.session, env.organization_id, viewer, filters)
    return ToolResult(
        {"requests": [_summary(env, row) for row in rows], "total_matching": total}, count=len(rows)
    )


async def get_request_details(env: ToolEnv, args: RequestRefArgs) -> ToolResult:
    row = await _load(env, args.ref)
    request = row.request
    actions = allowed_actions(request, await load_actor(env.session, env.membership))
    return ToolResult(
        {
            **_summary(env, row),
            "description": _truncate(request.description, DESCRIPTION_MAX_CHARS),
            "created_at": _minutes(request.created_at),
            "assigned_at": _minutes(request.assigned_at),
            "started_at": _minutes(request.started_at),
            "completed_at": _minutes(request.completed_at),
            "cancelled_at": _minutes(request.cancelled_at),
            # Advisory: what the user may do right now. Real actions are re-checked when taken.
            "your_allowed_actions": [action.value for action in actions],
        },
        count=1,
    )


async def get_request_history(env: ToolEnv, args: RequestRefArgs) -> ToolResult:
    row = await _load(env, args.ref)
    viewer = viewer_for(env.membership)
    events = await list_events(env.session, env.organization_id, row.request.id, viewer)
    comments = await list_comments(env.session, env.organization_id, row.request.id, viewer)
    items: list[tuple[datetime, dict[str, Any]]] = [
        (
            e.event.created_at,
            {
                "event": e.event.event_type,
                "by": e.actor_name,
                "from": e.event.from_status,
                "to": e.event.to_status,
                # Event data also holds membership ids: pass on only what's safe and useful.
                "assignee": e.event.data.get("assignee_name"),
                "claimed": e.event.data.get("claimed"),
            },
        )
        for e in events
    ] + [
        (c.comment.created_at, {"event": "comment", "by": c.author_name, "text": _truncate(c.comment.body, COMMENT_MAX_CHARS)})
        for c in comments
    ]
    items.sort(key=lambda item: item[0])
    shown = items[-HISTORY_MAX_ITEMS:]
    return ToolResult(
        {
            "ref": args.ref.upper(),
            "history": [{"at": _minutes(at), **{k: v for k, v in item.items() if v is not None}} for at, item in shown],
            "omitted_older": len(items) - len(shown),
        },
        count=len(shown),
    )


async def list_department_names(env: ToolEnv, _: NoArgs) -> ToolResult:
    departments = await list_departments(env.session, env.organization_id)
    return ToolResult({"departments": [d.name for d in departments]}, count=len(departments))


def _department_metrics(department: DepartmentMetrics) -> dict[str, Any]:
    metrics = {k: round(v, 1) if isinstance(v, float) else v for k, v in asdict(department.metrics).items()}
    return {"department": department.department_name, **metrics}


async def get_department_status(env: ToolEnv, args: DepartmentStatusArgs) -> ToolResult:
    # Comparing departments is one call, not one per department (one grouped query either way).
    department_id = await _department_id(env, args.department) if args.department else None
    _, departments = await organization_metrics(env.session, env.organization_id, timedelta(days=args.period_days))
    if department_id is None:
        rows = [_department_metrics(d) for d in departments]
        return ToolResult({"period_days": args.period_days, "departments": rows}, count=len(rows))
    department = next(d for d in departments if d.department_id == department_id)
    return ToolResult({"period_days": args.period_days, **_department_metrics(department)}, count=1)


async def list_staff(env: ToolEnv, args: DepartmentArgs) -> ToolResult:
    department_id = await _department_id(env, args.department)
    staff = await list_department_staff(env.session, env.organization_id, department_id)
    return ToolResult(
        {
            "department": args.department,
            "staff": [{"name": s.full_name, "role": s.role, "open_assignments": s.open_assignments} for s in staff],
        },
        count=len(staff),
    )


# --- registry -----------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[_Args]
    permission: Permission  # checked when offering AND again when executing
    run: Callable[[ToolEnv, Any], Awaitable[ToolResult]]


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        Tool(
            "search_requests",
            "Find requests by status, department, priority, assignee, title text or age. Newest first; "
            "total_matching counts all matches, not just those returned.",
            SearchRequestsArgs,
            Permission.REQUESTS_READ,
            search_requests,
        ),
        Tool(
            "get_request",
            "Full details of one request, including what the user may do with it now.",
            RequestRefArgs,
            Permission.REQUESTS_READ,
            get_request_details,
        ),
        Tool(
            "get_request_history",
            "Timeline of one request: status changes, assignments and comments.",
            RequestRefArgs,
            Permission.REQUESTS_READ,
            get_request_history,
        ),
        Tool(
            "list_departments",
            "Names of this organization's departments.",
            NoArgs,
            Permission.DEPARTMENTS_READ,
            list_department_names,
        ),
        Tool(
            "get_department_status",
            "Backlog (open, assigned, in progress) and flow metrics over the last period_days, for one department "
            "or, without department, for every department.",
            DepartmentStatusArgs,
            Permission.METRICS_READ,
            get_department_status,
        ),
        Tool(
            "list_department_staff",
            "Active staff of one department who could take its work, with their current open assignments.",
            DepartmentArgs,
            Permission.MEMBERS_READ,
            list_staff,
        ),
    )
}


def tools_for(role: MembershipRole) -> list[Tool]:
    """Only offer what the role may use: the model can't ask for what it never saw.
    (The executor still re-checks: offering is not authorization.)"""
    return [tool for tool in TOOLS.values() if has_permission(role, tool.permission)]


def _compact_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic's JSON schema, with $refs inlined and titles dropped: fewer tokens per call."""
    definitions = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                target = definitions[node["$ref"].rsplit("/", 1)[-1]]
                return walk({**target, **{k: v for k, v in node.items() if k != "$ref"}})
            return {k: walk(v) for k, v in node.items() if not (k == "title" and isinstance(v, str))}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(schema)


def tool_definition(tool: Tool) -> dict[str, Any]:
    """OpenAI-compatible function definition (the format Groq accepts)."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": _compact_schema(tool.args_model.model_json_schema()),
        },
    }
