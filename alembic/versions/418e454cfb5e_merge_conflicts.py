"""merge conflicts

Revision ID: 418e454cfb5e
Revises: 093629c276bd, 22f31128fd28
Create Date: 2026-03-29 15:31:50.558966

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '418e454cfb5e'
down_revision: Union[str, None] = ('093629c276bd', '22f31128fd28')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
