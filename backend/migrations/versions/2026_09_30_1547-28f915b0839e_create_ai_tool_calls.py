"""create ai tool calls

Reviewed: enum column as String + one named CHECK (autogenerate duplicated it); the
unique target on ai_usage is created before the composite FK that references it.

Revision ID: 28f915b0839e
Revises: a823bb894fb5
Create Date: 2026-09-30 15:47:20.426543

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28f915b0839e'
down_revision: Union[str, Sequence[str], None] = 'a823bb894fb5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(op.f('uq_ai_usage_organization_id_id'), 'ai_usage', ['organization_id', 'id'])
    op.create_table('ai_tool_calls',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('step', sa.SmallInteger(), nullable=False),
    sa.Column('tool', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('result_count', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("status IN ('ok', 'repeated', 'invalid_arguments', 'not_found', 'forbidden', 'ambiguous', 'unknown_tool', 'timeout', 'internal')", name=op.f('ck_ai_tool_calls_ai_tool_call_status')),
    sa.ForeignKeyConstraint(['organization_id', 'run_id'], ['ai_usage.organization_id', 'ai_usage.id'], name='fk_ai_tool_calls_run', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_ai_tool_calls_organization_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_tool_calls'))
    )
    op.create_index('ix_ai_tool_calls_org_run', 'ai_tool_calls', ['organization_id', 'run_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_ai_tool_calls_org_run', table_name='ai_tool_calls')
    op.drop_table('ai_tool_calls')
    op.drop_constraint(op.f('uq_ai_usage_organization_id_id'), 'ai_usage', type_='unique')
