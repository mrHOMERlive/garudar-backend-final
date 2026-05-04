"""merge conflicts

Revision ID: a6c44716f628
Revises: 2e970ce7209a, 34ed5d9c6ded
Create Date: 2026-03-26 16:48:25.765331

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6c44716f628'
down_revision: Union[str, None] = ('2e970ce7209a', '34ed5d9c6ded')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
