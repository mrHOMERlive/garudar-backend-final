"""merge conflicts

Revision ID: 093629c276bd
Revises: 033ceaf844a8, 594929a05ccd
Create Date: 2026-03-28 21:17:56.160758

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '093629c276bd'
down_revision: Union[str, None] = ('033ceaf844a8', '594929a05ccd')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
