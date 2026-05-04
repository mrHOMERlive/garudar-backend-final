"""merge conflicts

Revision ID: 6b58c62d7d3a
Revises: 7bd9a702cb29, c84737e0166c
Create Date: 2026-03-15 10:55:30.978967

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b58c62d7d3a'
down_revision: Union[str, None] = ('7bd9a702cb29', 'c84737e0166c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
