"""merge conflicts

Revision ID: f52398d45376
Revises: 0689c0c00d28
Create Date: 2026-02-03 18:59:10.423965

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f52398d45376'
down_revision: Union[str, None] = '0689c0c00d28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
