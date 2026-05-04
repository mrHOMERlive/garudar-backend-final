"""Add document_url and submitted_document_url to client_request_badges

Revision ID: add_nda_fields_001
Revises: 560fa9ca2a32
Create Date: 2026-02-12 13:47:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_nda_fields_001'
down_revision: Union[str, None] = '560fa9ca2a32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Добавляем поля document_url и submitted_document_url в client_request_badges
    op.add_column('client_request_badges', sa.Column('document_url', sa.Text(), nullable=True))
    op.add_column('client_request_badges', sa.Column('submitted_document_url', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('client_request_badges', 'submitted_document_url')
    op.drop_column('client_request_badges', 'document_url')
