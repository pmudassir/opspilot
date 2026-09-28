"""create comments

Revision ID: 42b901cdef8e
Revises: 5cc8b6070b46
Create Date: 2026-09-28 02:14:40.070472

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '42b901cdef8e'
down_revision: Union[str, Sequence[str], None] = '5cc8b6070b46'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('comments',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('author_membership_id', sa.Uuid(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id', 'author_membership_id'], ['memberships.organization_id', 'memberships.id'], name='fk_comments_author', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id', 'request_id'], ['requests.organization_id', 'requests.id'], name='fk_comments_request', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_comments_organization_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_comments'))
    )
    op.create_index('ix_comments_org_request_created', 'comments', ['organization_id', 'request_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_comments_org_request_created', table_name='comments')
    op.drop_table('comments')
