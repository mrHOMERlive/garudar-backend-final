"""NDA: signed_file_* columns + partner_country_en + partner_signatory_title_en

Revision ID: 2ca13599e880
Revises: a91f3d2bce47
Create Date: 2026-05-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2ca13599e880"
down_revision: Union[str, None] = "a91f3d2bce47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Поля для подписанной NDA (загружается клиентом после offline-подписи).
    op.add_column("nda_requests", sa.Column("signed_file_key", sa.String(500), nullable=True))
    op.add_column("nda_requests", sa.Column("signed_file_url", sa.Text(), nullable=True))
    op.add_column("nda_requests", sa.Column("signed_file_name", sa.String(255), nullable=True))
    op.add_column("nda_requests", sa.Column("signed_file_size", sa.BigInteger(), nullable=True))

    # Дополнительные поля партнёра для подстановки в DOCX-шаблон:
    # [POINT 3] страна incorporation, [POINT 5.1] title подписанта.
    op.add_column("nda_requests", sa.Column("partner_country_en", sa.String(100), nullable=True))
    op.add_column("nda_requests", sa.Column("partner_signatory_title_en", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("nda_requests", "partner_signatory_title_en")
    op.drop_column("nda_requests", "partner_country_en")
    op.drop_column("nda_requests", "signed_file_size")
    op.drop_column("nda_requests", "signed_file_name")
    op.drop_column("nda_requests", "signed_file_url")
    op.drop_column("nda_requests", "signed_file_key")
