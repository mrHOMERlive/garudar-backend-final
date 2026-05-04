"""merge conflicts

Revision ID: e3d6977341de
Revises: 0e9a8e50703a, 418e454cfb5e
Create Date: 2026-04-21 19:55:14.915228

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3d6977341de'
down_revision: Union[str, None] = ('0e9a8e50703a', '418e454cfb5e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
