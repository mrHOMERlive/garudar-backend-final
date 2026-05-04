"""merge conflicts

Revision ID: 0689c0c00d28
Revises: 84b42a77c2c4, add_badges_001
Create Date: 2026-02-03 11:00:40.801365

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0689c0c00d28'
down_revision: Union[str, None] = ('84b42a77c2c4', 'add_badges_001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
