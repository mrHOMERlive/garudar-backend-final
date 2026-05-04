"""merge conflicts

Revision ID: 30bb1adf0560
Revises: 154e02408bc0, f4d27eee370a
Create Date: 2026-02-06 09:33:11.539582

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '30bb1adf0560'
down_revision: Union[str, None] = ('154e02408bc0', 'f4d27eee370a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
