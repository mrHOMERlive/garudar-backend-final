"""pg_trgm extension + GIN indexes for entries fuzzy matching

Revision ID: a91f3d2bce47
Revises: e86bebb7b63f
Create Date: 2026-05-15 10:00:00.000000

Подключает расширение pg_trgm и строит GIN-индексы по `entries.name1`
и `entries.alias` для быстрого fuzzy-матчинга через
`func.similarity(...)`.

Используется сервисом `app/services/local_sanctions_screening.py`,
который ищет совпадения с DTTOT/DPPSPM/UN-AQ при KYC-скрининге.
Без индексов запрос работает линейно по таблице entries (~10к записей
терпимо, но индекс экономит ~80% latency).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a91f3d2bce47'
down_revision: Union[str, None] = 'e86bebb7b63f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pg_trgm нужен для func.similarity() — без него запрос упадёт
    # на стадии планирования. CREATE EXTENSION IF NOT EXISTS — идемпотентно.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # GIN-индексы по тригамам. Покрываем name1 (всегда заполнено) и
    # alias (склейка all aliases с разделителем "; ", тоже частый матч).
    # name2..name4 не индексируем — на практике редко содержат значимую
    # часть, и индексы по ним удвоят размер на диске без выигрыша.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_entries_name1_trgm "
        "ON entries USING gin (name1 gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_entries_alias_trgm "
        "ON entries USING gin (alias gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_entries_alias_trgm")
    op.execute("DROP INDEX IF EXISTS idx_entries_name1_trgm")
    # pg_trgm extension оставляем — оно может использоваться другими
    # запросами (текстовый поиск по другим таблицам). Удалять только
    # если уверены что больше нигде не используется.
