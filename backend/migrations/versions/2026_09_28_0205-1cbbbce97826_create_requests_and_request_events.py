"""create requests and request events

Reviewed: enum columns as String + one named CHECK each (autogenerate duplicated
them); append-only trigger on request_events added by hand.

Revision ID: 1cbbbce97826
Revises: d0b22bd30aa6
Create Date: 2026-09-28 02:05:39.656919

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1cbbbce97826'
down_revision: Union[str, Sequence[str], None] = 'd0b22bd30aa6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('requests',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('department_id', sa.Uuid(), nullable=False),
    sa.Column('requester_membership_id', sa.Uuid(), nullable=False),
    sa.Column('assignee_membership_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('status', sa.String(length=32), server_default='open', nullable=False),
    sa.Column('priority', sa.String(length=32), server_default='normal', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'open' AND assignee_membership_id IS NULL) OR (status IN ('assigned', 'in_progress', 'completed') AND assignee_membership_id IS NOT NULL) OR status = 'cancelled'", name=op.f('ck_requests_status_matches_assignee')),
    sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name=op.f('ck_requests_request_priority')),
    sa.CheckConstraint("status IN ('open', 'assigned', 'in_progress', 'completed', 'cancelled')", name=op.f('ck_requests_request_status')),
    sa.ForeignKeyConstraint(['organization_id', 'assignee_membership_id'], ['memberships.organization_id', 'memberships.id'], name='fk_requests_assignee', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id', 'department_id'], ['departments.organization_id', 'departments.id'], name='fk_requests_department', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id', 'requester_membership_id'], ['memberships.organization_id', 'memberships.id'], name='fk_requests_requester', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_requests_organization_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_requests')),
    sa.UniqueConstraint('organization_id', 'id', name=op.f('uq_requests_organization_id_id'))
    )
    op.create_index('ix_requests_org_created', 'requests', ['organization_id', sa.literal_column('created_at DESC'), sa.literal_column('id DESC')], unique=False)
    op.create_index('ix_requests_org_requester_created', 'requests', ['organization_id', 'requester_membership_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_table('request_events',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('actor_membership_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.String(length=32), nullable=False),
    sa.Column('from_status', sa.String(length=32), nullable=True),
    sa.Column('to_status', sa.String(length=32), nullable=True),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("event_type IN ('created', 'assigned', 'unassigned', 'status_changed')", name=op.f('ck_request_events_request_event_type')),
    sa.CheckConstraint("from_status IN ('open', 'assigned', 'in_progress', 'completed', 'cancelled')", name=op.f('ck_request_events_request_event_from_status')),
    sa.CheckConstraint("to_status IN ('open', 'assigned', 'in_progress', 'completed', 'cancelled')", name=op.f('ck_request_events_request_event_to_status')),
    sa.ForeignKeyConstraint(['organization_id', 'actor_membership_id'], ['memberships.organization_id', 'memberships.id'], name='fk_request_events_actor', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id', 'request_id'], ['requests.organization_id', 'requests.id'], name='fk_request_events_request', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_request_events_organization_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_request_events'))
    )
    op.create_index('ix_request_events_org_request_created', 'request_events', ['organization_id', 'request_id', 'created_at'], unique=False)
    # Audit log is append-only, enforced by the database for every writer.
    # (Row-level triggers don't fire on TRUNCATE, which the test suite uses.)
    op.execute(
        """
        CREATE FUNCTION forbid_request_event_changes() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'request_events is append-only (% rejected)', TG_OP;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER request_events_append_only
        BEFORE UPDATE OR DELETE ON request_events
        FOR EACH ROW EXECUTE FUNCTION forbid_request_event_changes()
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER request_events_append_only ON request_events")
    op.execute("DROP FUNCTION forbid_request_event_changes()")
    op.drop_index('ix_request_events_org_request_created', table_name='request_events')
    op.drop_table('request_events')
    op.drop_index('ix_requests_org_requester_created', table_name='requests')
    op.drop_index('ix_requests_org_created', table_name='requests')
    op.drop_table('requests')
