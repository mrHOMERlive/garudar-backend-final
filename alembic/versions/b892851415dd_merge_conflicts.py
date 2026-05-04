"""merge conflicts

Revision ID: b892851415dd
Revises: 67b7f943ae97, ec0049d0bd8f
Create Date: 2026-02-04 13:08:59.734016

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b892851415dd'
down_revision: Union[str, None] = ('67b7f943ae97', 'ec0049d0bd8f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
