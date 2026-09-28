"""add request lifecycle timestamps

Reviewed: autogenerate does not detect CHECK constraints on existing tables, so
they are added by hand, after a backfill that makes existing rows satisfy them.

Revision ID: 5cc8b6070b46
Revises: 1cbbbce97826
Create Date: 2026-09-28 02:13:49.454970

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5cc8b6070b46'
down_revision: Union[str, Sequence[str], None] = '1cbbbce97826'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CHECKS = {
    "ck_requests_completed_at_matches_status": "(status = 'completed') = (completed_at IS NOT NULL)",
    "ck_requests_cancelled_at_matches_status": "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
    "ck_requests_in_progress_has_started_at": "status <> 'in_progress' OR started_at IS NOT NULL",
}


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('requests', sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('requests', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('requests', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('requests', sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))

    # Backfill existing rows first, or the CHECKs below would fail on them.
    # Best available approximation for historical rows: the last update time.
    op.execute("UPDATE requests SET assigned_at = updated_at WHERE assignee_membership_id IS NOT NULL")
    op.execute("UPDATE requests SET started_at = updated_at WHERE status IN ('in_progress', 'completed')")
    op.execute("UPDATE requests SET completed_at = updated_at WHERE status = 'completed'")
    op.execute("UPDATE requests SET cancelled_at = updated_at WHERE status = 'cancelled'")

    for name, condition in CHECKS.items():
        op.create_check_constraint(op.f(name), 'requests', condition)


def downgrade() -> None:
    """Downgrade schema."""
    for name in CHECKS:
        op.drop_constraint(op.f(name), 'requests', type_='check')
    op.drop_column('requests', 'cancelled_at')
    op.drop_column('requests', 'completed_at')
    op.drop_column('requests', 'started_at')
    op.drop_column('requests', 'assigned_at')
