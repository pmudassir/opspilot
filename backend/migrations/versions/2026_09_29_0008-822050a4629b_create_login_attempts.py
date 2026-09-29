"""create login attempts

Revision ID: 822050a4629b
Revises: 42b901cdef8e
Create Date: 2026-09-29 00:08:32.855505

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '822050a4629b'
down_revision: Union[str, Sequence[str], None] = '42b901cdef8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('login_attempts',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=False),
    sa.Column('succeeded', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_login_attempts'))
    )
    op.create_index('ix_login_attempts_email_created_at', 'login_attempts', ['email', 'created_at'], unique=False)
    op.create_index('ix_login_attempts_ip_created_at', 'login_attempts', ['ip', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_login_attempts_ip_created_at', table_name='login_attempts')
    op.drop_index('ix_login_attempts_email_created_at', table_name='login_attempts')
    op.drop_table('login_attempts')
