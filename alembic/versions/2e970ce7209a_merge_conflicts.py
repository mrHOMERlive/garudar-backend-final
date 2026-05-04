"""merge conflicts

Revision ID: 2e970ce7209a
Revises: 6b58c62d7d3a, eb922fbb5c78
Create Date: 2026-03-21 21:26:04.265695

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2e970ce7209a'
down_revision: Union[str, None] = ('6b58c62d7d3a', 'eb922fbb5c78')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
