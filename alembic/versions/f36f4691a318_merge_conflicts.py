"""merge conflicts

Revision ID: f36f4691a318
Revises: ce48c543699a
Create Date: 2026-02-03 19:22:34.153170

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f36f4691a318'
down_revision: Union[str, None] = 'ce48c543699a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
