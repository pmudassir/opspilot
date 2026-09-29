import uuid
from dataclasses import asdict
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.db import SessionDep
from app.metrics.service import organization_metrics
from app.permissions import Permission
from app.tenancy import authorized

router = APIRouter(prefix="/api/v1/orgs/{org_id}/metrics", tags=["metrics"])

DEFAULT_PERIOD_DAYS = 30
MAX_PERIOD_DAYS = 365


class FlowMetricsOut(BaseModel):
    open: int
    assigned: int
    in_progress: int
    created_in_period: int
    completed_in_period: int
    cancelled_in_period: int
    median_hours_to_assign: float | None
    p90_hours_to_assign: float | None
    median_hours_to_complete: float | None
    p90_hours_to_complete: float | None


class DepartmentMetricsOut(FlowMetricsOut):
    department_id: uuid.UUID
    department_name: str


class MetricsOut(BaseModel):
    period_days: int
    totals: FlowMetricsOut
    departments: list[DepartmentMetricsOut]


@router.get("")
async def get_metrics(
    context: authorized(Permission.METRICS_READ),  # type: ignore[valid-type]
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=MAX_PERIOD_DAYS)] = DEFAULT_PERIOD_DAYS,
) -> MetricsOut:
    totals, departments = await organization_metrics(
        session, context.organization_id, timedelta(days=days)
    )
    return MetricsOut(
        period_days=days,
        totals=FlowMetricsOut(**asdict(totals)),
        departments=[
            DepartmentMetricsOut(
                department_id=d.department_id,
                department_name=d.department_name,
                **asdict(d.metrics),
            )
            for d in departments
        ],
    )
