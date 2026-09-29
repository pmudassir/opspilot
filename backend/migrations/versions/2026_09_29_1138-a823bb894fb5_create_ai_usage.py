"""create ai usage

Reviewed: enum column as String + one named CHECK (autogenerate duplicated it).

Revision ID: a823bb894fb5
Revises: 822050a4629b
Create Date: 2026-09-29 11:38:13.435307

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a823bb894fb5'
down_revision: Union[str, Sequence[str], None] = '822050a4629b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ai_usage',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('membership_id', sa.Uuid(), nullable=False),
    sa.Column('feature', sa.String(length=64), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('prompt_version', sa.String(length=64), nullable=False),
    sa.Column('outcome', sa.String(length=32), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("outcome IN ('success', 'timeout', 'rate_limited', 'provider_error', 'invalid_output')", name=op.f('ck_ai_usage_ai_usage_outcome')),
    sa.ForeignKeyConstraint(['organization_id', 'membership_id'], ['memberships.organization_id', 'memberships.id'], name='fk_ai_usage_membership', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_ai_usage_organization_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_usage'))
    )
    op.create_index('ix_ai_usage_org_membership_created', 'ai_usage', ['organization_id', 'membership_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_ai_usage_org_membership_created', table_name='ai_usage')
    op.drop_table('ai_usage')
