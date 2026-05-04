"""merge conflicts

Revision ID: bf89d5628ac7
Revises: f36f4691a318
Create Date: 2026-02-04 12:49:35.035987

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bf89d5628ac7'
down_revision: Union[str, None] = 'f36f4691a318'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
