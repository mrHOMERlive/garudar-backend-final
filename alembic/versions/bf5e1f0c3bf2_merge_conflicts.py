"""merge conflicts

Revision ID: bf5e1f0c3bf2
Revises: 09608b4c0b59, ac190bf52f81
Create Date: 2026-03-07 19:49:01.868777

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bf5e1f0c3bf2'
down_revision: Union[str, None] = ('09608b4c0b59', 'ac190bf52f81')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
