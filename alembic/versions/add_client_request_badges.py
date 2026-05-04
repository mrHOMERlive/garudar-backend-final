"""add client_request_badges table and account status fields

Revision ID: add_badges_001
Revises: fbf49e28d02d
Create Date: 2025-02-03 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_badges_001'
down_revision: Union[str, None] = 'fbf49e28d02d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Добавляем поля в таблицу clients
    op.add_column('clients', sa.Column('account_status', sa.String(length=50), nullable=False, server_default='active'))
    op.add_column('clients', sa.Column('account_hold_reason', sa.Text(), nullable=True))

    # Создаем таблицу client_request_badges
    op.create_table(
        'client_request_badges',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('client_id', sa.String(length=255), nullable=False),
        sa.Column('badge_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='not_required'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('staff_comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.client_id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Создаем индексы
    op.create_index('idx_badge_client', 'client_request_badges', ['client_id'], unique=False)
    op.create_index('idx_badge_client_type', 'client_request_badges', ['client_id', 'badge_type'], unique=True)
    op.create_index('idx_badge_active', 'client_request_badges', ['is_active'], unique=False)


def downgrade() -> None:
    # Удаляем индексы
    op.drop_index('idx_badge_active', table_name='client_request_badges')
    op.drop_index('idx_badge_client_type', table_name='client_request_badges')
    op.drop_index('idx_badge_client', table_name='client_request_badges')
    
    # Удаляем таблицу
    op.drop_table('client_request_badges')
    
    # Удаляем поля из clients
    op.drop_column('clients', 'account_hold_reason')
    op.drop_column('clients', 'account_status')
