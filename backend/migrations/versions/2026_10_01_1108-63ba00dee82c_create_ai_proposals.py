"""create ai proposals

Reviewed: enum columns as String + one named CHECK each (autogenerate duplicated them).

Revision ID: 63ba00dee82c
Revises: 905a45f0e80e
Create Date: 2026-10-01 11:08:17.743419

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '63ba00dee82c'
down_revision: Union[str, Sequence[str], None] = '905a45f0e80e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ai_proposals',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('proposer_membership_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('new_assignee_membership_id', sa.Uuid(), nullable=True),
    sa.Column('new_priority', sa.String(length=32), nullable=True),
    sa.Column('comment_body', sa.Text(), nullable=True),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decided_by_membership_id', sa.Uuid(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_code', sa.String(length=32), nullable=True),
    sa.Column('failure_detail', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("(action = 'assign') = (new_assignee_membership_id IS NOT NULL)", name=op.f('ck_ai_proposals_assign_has_assignee')),
    sa.CheckConstraint("(action = 'change_priority') = (new_priority IS NOT NULL)", name=op.f('ck_ai_proposals_priority_has_priority')),
    sa.CheckConstraint("(action = 'comment') = (comment_body IS NOT NULL)", name=op.f('ck_ai_proposals_comment_has_body')),
    sa.CheckConstraint("(status = 'failed') = (failure_code IS NOT NULL)", name=op.f('ck_ai_proposals_failure_matches_status')),
    sa.CheckConstraint("(status IN ('pending', 'expired')) = (decided_by_membership_id IS NULL AND decided_at IS NULL)", name=op.f('ck_ai_proposals_decided_matches_status')),
    sa.CheckConstraint("action IN ('assign', 'unassign', 'cancel', 'change_priority', 'comment')", name=op.f('ck_ai_proposals_ai_proposal_action')),
    sa.CheckConstraint("new_priority IN ('low', 'normal', 'high', 'urgent')", name=op.f('ck_ai_proposals_ai_proposal_priority')),
    sa.CheckConstraint("status IN ('pending', 'executed', 'failed', 'rejected', 'expired')", name=op.f('ck_ai_proposals_ai_proposal_status')),
    sa.ForeignKeyConstraint(['organization_id', 'decided_by_membership_id'], ['memberships.organization_id', 'memberships.id'], name='fk_ai_proposals_decided_by', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id', 'new_assignee_membership_id'], ['memberships.organization_id', 'memberships.id'], name='fk_ai_proposals_new_assignee', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id', 'proposer_membership_id'], ['memberships.organization_id', 'memberships.id'], name='fk_ai_proposals_proposer', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id', 'run_id'], ['ai_usage.organization_id', 'ai_usage.id'], name='fk_ai_proposals_run', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_ai_proposals_organization_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_proposals')),
    sa.UniqueConstraint('organization_id', 'id', name=op.f('uq_ai_proposals_organization_id_id'))
    )
    op.create_index('ix_ai_proposals_org_proposer_created', 'ai_proposals', ['organization_id', 'proposer_membership_id', 'created_at'], unique=False)
    op.create_table('ai_proposal_items',
    sa.Column('proposal_id', sa.Uuid(), nullable=False),
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.SmallInteger(), nullable=False),
    sa.Column('expected_updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('priority', sa.String(length=32), nullable=False),
    sa.Column('assignee_name', sa.String(length=200), nullable=True),
    sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name=op.f('ck_ai_proposal_items_ai_proposal_item_priority')),
    sa.CheckConstraint("status IN ('open', 'assigned', 'in_progress', 'completed', 'cancelled')", name=op.f('ck_ai_proposal_items_ai_proposal_item_status')),
    sa.ForeignKeyConstraint(['organization_id', 'proposal_id'], ['ai_proposals.organization_id', 'ai_proposals.id'], name='fk_ai_proposal_items_proposal', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id', 'request_id'], ['requests.organization_id', 'requests.id'], name='fk_ai_proposal_items_request', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_ai_proposal_items_organization_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('proposal_id', 'request_id', name=op.f('pk_ai_proposal_items'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('ai_proposal_items')
    op.drop_index('ix_ai_proposals_org_proposer_created', table_name='ai_proposals')
    op.drop_table('ai_proposals')
