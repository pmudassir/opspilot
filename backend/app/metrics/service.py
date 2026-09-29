"""Operational metrics, computed in Postgres (grouped aggregates + percentiles).

Definitions (see docs/metrics.md):
- backlog: requests currently open / assigned / in progress (not period-bound)
- created/completed/cancelled_in_period: events whose timestamp falls in the last N days
- hours_to_assign: created_at → first assignment, for requests created in the period
- hours_to_complete: created_at → completed_at, for requests completed in the period
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, case, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.departments.models import Department
from app.requests.models import Request, RequestStatus

SECONDS_PER_HOUR = 3600


@dataclass(frozen=True)
class FlowMetrics:
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


@dataclass(frozen=True)
class DepartmentMetrics:
    department_id: uuid.UUID
    department_name: str
    metrics: FlowMetrics


def _count_where(condition: ColumnElement[bool]) -> ColumnElement[int]:
    return func.count().filter(condition)


def _hours(later: Any, earlier: Any) -> ColumnElement[float]:
    return extract("epoch", later - earlier) / SECONDS_PER_HOUR


def _percentile(fraction: float, value: ColumnElement[float], condition: ColumnElement[bool]):  # noqa: ANN202
    # Rows not matching `condition` become NULL, which percentile_cont ignores.
    return func.percentile_cont(fraction).within_group(case((condition, value)))


def _aggregates(period: timedelta) -> list[ColumnElement[Any]]:
    since = func.now() - period
    created_in = Request.created_at >= since
    completed_in = and_(Request.status == RequestStatus.COMPLETED, Request.completed_at >= since)
    assigned_in = and_(created_in, Request.assigned_at.is_not(None))
    to_assign = _hours(Request.assigned_at, Request.created_at)
    to_complete = _hours(Request.completed_at, Request.created_at)
    return [
        _count_where(Request.status == RequestStatus.OPEN).label("open"),
        _count_where(Request.status == RequestStatus.ASSIGNED).label("assigned"),
        _count_where(Request.status == RequestStatus.IN_PROGRESS).label("in_progress"),
        _count_where(created_in).label("created_in_period"),
        _count_where(completed_in).label("completed_in_period"),
        _count_where(
            and_(Request.status == RequestStatus.CANCELLED, Request.cancelled_at >= since)
        ).label("cancelled_in_period"),
        _percentile(0.5, to_assign, assigned_in).label("median_hours_to_assign"),
        _percentile(0.9, to_assign, assigned_in).label("p90_hours_to_assign"),
        _percentile(0.5, to_complete, completed_in).label("median_hours_to_complete"),
        _percentile(0.9, to_complete, completed_in).label("p90_hours_to_complete"),
    ]


def _flow(row: Any) -> FlowMetrics:
    def hours(value: float | None) -> float | None:
        return None if value is None else round(float(value), 2)

    return FlowMetrics(
        open=row.open or 0,
        assigned=row.assigned or 0,
        in_progress=row.in_progress or 0,
        created_in_period=row.created_in_period or 0,
        completed_in_period=row.completed_in_period or 0,
        cancelled_in_period=row.cancelled_in_period or 0,
        median_hours_to_assign=hours(row.median_hours_to_assign),
        p90_hours_to_assign=hours(row.p90_hours_to_assign),
        median_hours_to_complete=hours(row.median_hours_to_complete),
        p90_hours_to_complete=hours(row.p90_hours_to_complete),
    )


def _per_department(organization_id: uuid.UUID, period: timedelta) -> Select[Any]:
    # LEFT JOIN from departments so departments without requests still appear (with zeros).
    return (
        select(Department.id, Department.name, *_aggregates(period))
        .outerjoin(
            Request,
            and_(
                Request.organization_id == Department.organization_id,
                Request.department_id == Department.id,
            ),
        )
        .where(Department.organization_id == organization_id)
        .group_by(Department.id, Department.name)
        .order_by(Department.name)
    )


async def organization_metrics(
    session: AsyncSession, organization_id: uuid.UUID, period: timedelta
) -> tuple[FlowMetrics, list[DepartmentMetrics]]:
    """Org-wide totals and per-department metrics. Percentiles can't be combined from
    per-department results, so totals are a separate (ungrouped) aggregate."""
    totals = (
        await session.execute(
            select(*_aggregates(period)).where(Request.organization_id == organization_id)
        )
    ).one()
    rows = (await session.execute(_per_department(organization_id, period))).all()
    departments = [DepartmentMetrics(row.id, row.name, _flow(row)) for row in rows]
    return _flow(totals), departments
