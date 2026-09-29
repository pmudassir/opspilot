import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.ai import service
from app.ai.dependencies import DrafterDep
from app.config import SettingsDep
from app.db import SessionDep
from app.errors import UnprocessableError
from app.permissions import Permission
from app.requests.models import RequestPriority
from app.schemas import StrictRequest, trimmed_str
from app.tenancy import authorized

router = APIRouter(prefix="/api/v1/orgs/{org_id}/ai", tags=["ai"])

DRAFT_TEXT_MIN = 10
DRAFT_TEXT_MAX = 2000  # bounds cost per call


class RequestDraftBody(StrictRequest):
    text: trimmed_str(DRAFT_TEXT_MAX)  # type: ignore[valid-type]


class RequestDraftOut(BaseModel):
    """A suggestion only: the client shows it in the form for the person to review and submit."""

    title: str
    description: str
    department_id: uuid.UUID | None
    department_name: str | None
    priority: RequestPriority
    rationale: str
    model: str


@router.post("/request-drafts")
async def draft_request(
    body: RequestDraftBody,
    context: authorized(Permission.REQUESTS_CREATE),  # type: ignore[valid-type]
    session: SessionDep,
    settings: SettingsDep,
    drafter: DrafterDep,
) -> RequestDraftOut:
    if len(body.text) < DRAFT_TEXT_MIN:
        raise UnprocessableError(f"Describe the problem in at least {DRAFT_TEXT_MIN} characters.")
    result = await service.draft_request(
        session,
        organization_id=context.organization_id,
        membership_id=context.membership.id,
        text=body.text,
        drafter=drafter,
        quota_per_hour=settings.ai_drafts_per_hour,
    )
    return RequestDraftOut(**result.__dict__)
