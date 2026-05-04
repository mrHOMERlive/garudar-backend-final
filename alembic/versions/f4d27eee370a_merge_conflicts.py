"""merge conflicts

Revision ID: f4d27eee370a
Revises: b892851415dd, f4249ba8ff15
Create Date: 2026-02-04 16:09:30.368905

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4d27eee370a'
down_revision: Union[str, None] = ('b892851415dd', 'f4249ba8ff15')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
