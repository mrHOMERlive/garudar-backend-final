"""merge conflicts

Revision ID: 594929a05ccd
Revises: a6c44716f628, e3786b3bed0f
Create Date: 2026-03-27 21:22:47.360193

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '594929a05ccd'
down_revision: Union[str, None] = ('a6c44716f628', 'e3786b3bed0f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
