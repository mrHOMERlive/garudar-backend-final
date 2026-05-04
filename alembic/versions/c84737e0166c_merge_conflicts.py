"""merge conflicts

Revision ID: c84737e0166c
Revises: bf5e1f0c3bf2, f73916971801
Create Date: 2026-03-09 22:04:20.720150

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c84737e0166c'
down_revision: Union[str, None] = ('bf5e1f0c3bf2', 'f73916971801')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
