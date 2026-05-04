"""add refresh tokens table

Revision ID: f4249ba8ff15
Revises: 67b7f943ae97
Create Date: 2026-02-04 18:35:50.624373

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4249ba8ff15'
down_revision: Union[str, None] = '67b7f943ae97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'refresh_tokens',
        sa.Column('token_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('token_hash', sa.String(255), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('token_id'),
        sa.UniqueConstraint('token_hash')
    )
    
    op.create_index('idx_refresh_token_hash', 'refresh_tokens', ['token_hash'])
    op.create_index('idx_refresh_user_id', 'refresh_tokens', ['user_id'])
    op.create_index('idx_refresh_expires', 'refresh_tokens', ['expires_at'])


def downgrade() -> None:
    op.drop_index('idx_refresh_expires', table_name='refresh_tokens')
    op.drop_index('idx_refresh_user_id', table_name='refresh_tokens')
    op.drop_index('idx_refresh_token_hash', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
