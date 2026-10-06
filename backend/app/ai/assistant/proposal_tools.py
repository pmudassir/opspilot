"""Tools that PROPOSE changes. They never change anything.

Each resolves which requests the change would touch (refs the user has seen, or the
same filters as search_requests: the server counts and resolves, not the model),
checks every request as this user could act on it right now, and returns a draft.
The service stores the draft as a pending proposal; only the user can approve it.
"""

import uuid
from typing import Self

from pydantic import Field, model_validator

from app.ai.assistant.tools import (
    Ref,
    SearchFilters,
    Tool,
    ToolArgs,
    ToolEnv,
    ToolError,
    ToolErrorCode,
    ToolResult,
    person_membership_id,
    resolve_filters,
)
from app.ai.proposals.models import ProposalAction
from app.ai.proposals.service import (
    MAX_ITEMS,
    NothingToProposeError,
    describe,
    draft_proposal,
)
from app.comments.models import COMMENT_BODY_MAX_LENGTH
from app.errors import NotFoundError, UnprocessableError
from app.permissions import Permission
from app.requests.models import RequestPriority
from app.requests.service import count_requests, list_requests, viewer_for


class ProposalTarget(ToolArgs):
    refs: list[Ref] | None = Field(
        None, min_length=1, max_length=MAX_ITEMS, description="Requests from earlier results"
    )
    filters: SearchFilters | None = Field(None, description="Or every request matching these filters")

    @model_validator(mode="after")
    def _exactly_one_target(self) -> Self:
        if (self.refs is None) == (self.filters is None):
            raise ValueError("Give either refs or filters")
        return self


class ProposeAssignArgs(ProposalTarget):
    assignee: str = Field(min_length=1, max_length=100, description='"me" or a person\'s full name')


class ProposeUnassignArgs(ProposalTarget):
    pass


class ProposeCancelArgs(ProposalTarget):
    pass


class ProposePriorityArgs(ProposalTarget):
    priority: RequestPriority


class ProposeCommentArgs(ToolArgs):
    ref: Ref
    text: str = Field(min_length=1, max_length=COMMENT_BODY_MAX_LENGTH)


async def _target_ids(env: ToolEnv, target: ProposalTarget) -> list[uuid.UUID]:
    if target.refs is not None:
        ids = []
        for ref in target.refs:
            request_id = env.refs.resolve(ref)
            if request_id is None:
                raise ToolError(ToolErrorCode.NOT_FOUND, f"Unknown ref {ref}. Find requests with search_requests first.")
            ids.append(request_id)
        return ids
    assert target.filters is not None
    filters = await resolve_filters(env, target.filters)
    viewer = viewer_for(env.membership)
    total = await count_requests(env.session, env.organization_id, viewer, filters)
    if total == 0:
        raise ToolError(ToolErrorCode.NOT_FOUND, "No requests match those filters.")
    if total > MAX_ITEMS:
        raise ToolError(
            ToolErrorCode.INVALID_ARGUMENTS,
            f"{total} requests match; a proposal can change at most {MAX_ITEMS}. Narrow the filters.",
        )
    rows, _ = await list_requests(env.session, env.organization_id, viewer, filters, limit=MAX_ITEMS, after=None)
    return [row.request.id for row in rows]


async def _propose(env: ToolEnv, action: ProposalAction, request_ids: list[uuid.UUID], **params: object) -> ToolResult:
    try:
        draft = await draft_proposal(env.session, env.organization_id, env.membership, action, request_ids, **params)  # type: ignore[arg-type]
    except NothingToProposeError as exc:
        raise ToolError(ToolErrorCode.FORBIDDEN, exc.detail) from None
    except NotFoundError:
        raise ToolError(ToolErrorCode.NOT_FOUND, "A request doesn't exist or isn't visible to you.") from None
    except UnprocessableError as exc:
        raise ToolError(ToolErrorCode.INVALID_ARGUMENTS, exc.detail) from None
    summary = describe(action, len(draft.items), assignee=draft.new_assignee_name, priority=draft.new_priority)
    return ToolResult(
        {
            "proposal": "P1",
            "summary": summary,
            "requests": [
                {"ref": env.refs.ref_for(i.request_id), "title": i.title, "status": i.status, "priority": i.priority}
                for i in draft.items
            ],
            "excluded": [
                {"ref": env.refs.ref_for(e.request_id), "title": e.title, "reason": e.reason} for e in draft.excluded
            ],
            "state": "Waiting for the user to approve or reject it in the app. Nothing has changed yet.",
        },
        count=len(draft.items),
        proposal=draft,
    )


async def propose_assign(env: ToolEnv, args: ProposeAssignArgs) -> ToolResult:
    assignee = env.membership.id if args.assignee.casefold() == "me" else await person_membership_id(env, args.assignee)
    return await _propose(env, ProposalAction.ASSIGN, await _target_ids(env, args), new_assignee_membership_id=assignee)


async def propose_unassign(env: ToolEnv, args: ProposeUnassignArgs) -> ToolResult:
    return await _propose(env, ProposalAction.UNASSIGN, await _target_ids(env, args))


async def propose_cancel(env: ToolEnv, args: ProposeCancelArgs) -> ToolResult:
    return await _propose(env, ProposalAction.CANCEL, await _target_ids(env, args))


async def propose_priority(env: ToolEnv, args: ProposePriorityArgs) -> ToolResult:
    return await _propose(env, ProposalAction.CHANGE_PRIORITY, await _target_ids(env, args), new_priority=args.priority)


async def propose_comment(env: ToolEnv, args: ProposeCommentArgs) -> ToolResult:
    request_id = env.refs.resolve(args.ref)
    if request_id is None:
        raise ToolError(ToolErrorCode.NOT_FOUND, f"Unknown ref {args.ref}. Find the request with search_requests first.")
    return await _propose(env, ProposalAction.COMMENT, [request_id], comment_body=args.text)


_NOTE = "Creates a proposal the user must approve in the app; nothing changes until they do."

PROPOSAL_TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        Tool("propose_assign", f"Propose assigning requests to someone. {_NOTE}", ProposeAssignArgs,
             Permission.REQUESTS_ASSIGN, propose_assign, proposes=True),
        Tool("propose_unassign", f"Propose unassigning requests. {_NOTE}", ProposeUnassignArgs,
             Permission.REQUESTS_ASSIGN, propose_unassign, proposes=True),
        Tool("propose_cancel", f"Propose cancelling requests. {_NOTE}", ProposeCancelArgs,
             Permission.REQUESTS_READ, propose_cancel, proposes=True),
        Tool("propose_priority", f"Propose changing requests' priority. {_NOTE}", ProposePriorityArgs,
             Permission.REQUESTS_PRIORITIZE, propose_priority, proposes=True),
        Tool("propose_comment", f"Propose adding a comment to one request. {_NOTE}", ProposeCommentArgs,
             Permission.REQUESTS_COMMENT, propose_comment, proposes=True),
    )
}
