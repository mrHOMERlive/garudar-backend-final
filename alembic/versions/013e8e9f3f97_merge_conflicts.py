"""merge conflicts

Revision ID: 013e8e9f3f97
Revises: 45a1a398984c, ec43dfca446d
Create Date: 2026-02-23 20:38:53.439013

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '013e8e9f3f97'
down_revision: Union[str, None] = ('45a1a398984c', 'ec43dfca446d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
