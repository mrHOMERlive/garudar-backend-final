"""merge conflicts

Revision ID: ec43dfca446d
Revises: 69ca2068805d, add_nda_fields_001
Create Date: 2026-02-15 13:03:40.005813

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ec43dfca446d'
down_revision: Union[str, None] = ('69ca2068805d', 'add_nda_fields_001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
