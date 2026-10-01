"""add priority changed event

The event type is a VARCHAR + CHECK (ADR-009): changing the allowed values is a
constraint swap. Downgrade can't delete priority_changed events (request_events is
append-only), so it restores the old CHECK as NOT VALID: existing rows stay, new
ones are checked.

Revision ID: 905a45f0e80e
Revises: 28f915b0839e
Create Date: 2026-10-01 10:59:17.769037

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '905a45f0e80e'
down_revision: Union[str, Sequence[str], None] = '28f915b0839e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT = "ck_request_events_request_event_type"
OLD = "event_type IN ('created', 'assigned', 'unassigned', 'status_changed')"
NEW = "event_type IN ('created', 'assigned', 'unassigned', 'status_changed', 'priority_changed')"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f(CONSTRAINT), "request_events", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "request_events", NEW)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f(CONSTRAINT), "request_events", type_="check")
    op.execute(f"ALTER TABLE request_events ADD CONSTRAINT {CONSTRAINT} CHECK ({OLD}) NOT VALID")
