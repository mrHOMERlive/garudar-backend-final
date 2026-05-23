"""add aml local prescreen columns to onboarding_kyc_profiles

Revision ID: 888cff42781c
Revises: ed6b73328198
Create Date: 2026-05-23 11:22:16.296663

Добавляет 4 колонки в onboarding_kyc_profiles для отслеживания результатов
локального PPATK-pre-screen, который запускается на KYC submit (бесплатный
fuzzy-матч против таблицы entries) ДО ComplyAdvantage-проверки на approve.

- aml_local_screening_status: pending | completed | error | NULL (не было pre-screen)
- aml_local_screening_at: timestamp последнего запуска
- aml_local_match_count: число PPATK-матчей (для UI-бейджа)
- aml_local_red_flag: булев флаг хоть-одно-совпадение (для partial index)

server_default обеспечивает безопасный backfill для существующих строк без
блокировки таблицы при ALTER. Все колонки добавляются за один атомарный
DDL-блок Alembic'а.

Partial GIN-index на aml_local_red_flag=true резко ускоряет фильтр Staff
KYC Queue по red_flag (значение редкое — ожидаем <1% строк).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '888cff42781c'
down_revision: Union[str, None] = 'ed6b73328198'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'onboarding_kyc_profiles',
        sa.Column('aml_local_screening_status', sa.String(length=50), nullable=True),
    )
    op.add_column(
        'onboarding_kyc_profiles',
        sa.Column('aml_local_screening_at', sa.DateTime(), nullable=True),
    )
    op.add_column(
        'onboarding_kyc_profiles',
        sa.Column('aml_local_match_count', sa.Integer(), server_default='0', nullable=False),
    )
    op.add_column(
        'onboarding_kyc_profiles',
        sa.Column('aml_local_red_flag', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )
    op.create_index(
        'idx_kyc_profile_red_flag',
        'onboarding_kyc_profiles',
        ['aml_local_red_flag'],
        unique=False,
        postgresql_where=sa.text('aml_local_red_flag = true'),
    )


def downgrade() -> None:
    op.drop_index(
        'idx_kyc_profile_red_flag',
        table_name='onboarding_kyc_profiles',
        postgresql_where=sa.text('aml_local_red_flag = true'),
    )
    op.drop_column('onboarding_kyc_profiles', 'aml_local_red_flag')
    op.drop_column('onboarding_kyc_profiles', 'aml_local_match_count')
    op.drop_column('onboarding_kyc_profiles', 'aml_local_screening_at')
    op.drop_column('onboarding_kyc_profiles', 'aml_local_screening_status')
