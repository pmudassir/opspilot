"""create departments and department members

Reviewed: moved uq_memberships_organization_id_id before the composite FK that
references it (and after it on downgrade); autogenerate ordered it wrong.

Revision ID: d0b22bd30aa6
Revises: aaa2277633d2
Create Date: 2026-09-28 01:55:46.017742

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0b22bd30aa6'
down_revision: Union[str, Sequence[str], None] = 'aaa2277633d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Must exist before department_members' composite FK references it.
    op.create_unique_constraint(op.f('uq_memberships_organization_id_id'), 'memberships', ['organization_id', 'id'])
    op.create_table('departments',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_departments_organization_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_departments')),
    sa.UniqueConstraint('organization_id', 'id', name=op.f('uq_departments_organization_id_id'))
    )
    op.create_index('uq_departments_organization_id_lower_name', 'departments', ['organization_id', sa.literal_column('lower(name)')], unique=True)
    op.create_table('department_members',
    sa.Column('department_id', sa.Uuid(), nullable=False),
    sa.Column('membership_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id', 'department_id'], ['departments.organization_id', 'departments.id'], name='fk_department_members_department', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id', 'membership_id'], ['memberships.organization_id', 'memberships.id'], name='fk_department_members_membership', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_department_members_organization_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('department_id', 'membership_id', name=op.f('pk_department_members'))
    )
    op.create_index('ix_department_members_organization_id_membership_id', 'department_members', ['organization_id', 'membership_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_department_members_organization_id_membership_id', table_name='department_members')
    op.drop_table('department_members')
    op.drop_index('uq_departments_organization_id_lower_name', table_name='departments')
    op.drop_table('departments')
    # Dropped last: department_members' composite FK depended on it.
    op.drop_constraint(op.f('uq_memberships_organization_id_id'), 'memberships', type_='unique')
