"""merge conflicts

Revision ID: 69ca2068805d
Revises: 30bb1adf0560, 560fa9ca2a32
Create Date: 2026-02-07 08:42:32.885063

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69ca2068805d'
down_revision: Union[str, None] = ('30bb1adf0560', '560fa9ca2a32')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
