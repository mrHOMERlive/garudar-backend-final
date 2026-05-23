"""fix inconsistent prescreen counters

Revision ID: 31b6c2297cab
Revises: 888cff42781c
Create Date: 2026-05-23 18:11:32.190923

Одноразовый data-cleanup для случаев когда `OnboardingKycProfile.aml_local_*`
счётчики говорят «есть PPATK-матчи», а реальных AmlAlert/AmlCustomer в БД нет.

Источник проблемы — баг в `auto_screen_on_kyc_approval` (исправлен отдельно
в `app/services/aml_auto_screening.py`): cleanup pre-screen-записей удалял
AmlCustomer/AmlAlert, но не сбрасывал кэширующие счётчики `aml_local_red_flag`
и `aml_local_match_count` на самом профиле. В результате Staff KYC Queue
показывал красный «PPATK Red Flag» бейдж, а Drawer открывался пустой
(«No matches against local PPATK lists»).

Эта миграция приводит существующие inconsistent профили к консистентному
состоянию. Затрагивает только профили с `aml_local_red_flag = true`, у
которых НЕТ соответствующих pre-screen `AmlAlert`'ов в БД. Новые
профили после фикса самой функции в такое состояние попадать не должны.

downgrade — no-op (это data-cleanup, не структурное изменение).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '31b6c2297cab'
down_revision: Union[str, None] = '888cff42781c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Сбрасываем счётчики только для тех профилей, чьи pre-screen `AmlAlert`'ы
    # (match_type='ppatk_local' под `AmlCustomer` с screening_result='PRESCREEN_ONLY'
    # и customer_identifier IS NULL) не существуют в БД — это inconsistent state.
    op.execute(sa.text("""
        UPDATE onboarding_kyc_profiles p
        SET aml_local_red_flag = false,
            aml_local_match_count = 0
        WHERE p.aml_local_red_flag = true
          AND NOT EXISTS (
              SELECT 1
              FROM aml_customers c
              JOIN aml_alerts a ON a.aml_customer_id = c.id
              WHERE c.client_id = p.client_id
                AND c.customer_identifier IS NULL
                AND c.screening_result = 'PRESCREEN_ONLY'
                AND a.match_type = 'ppatk_local'
          );
    """))


def downgrade() -> None:
    # No-op: data cleanup нельзя «откатить» — мы не знаем, какие именно счётчики
    # были до миграции. Структурных изменений нет.
    pass
