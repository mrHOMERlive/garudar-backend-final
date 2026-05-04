"""merge conflicts

Revision ID: 09608b4c0b59
Revises: 013e8e9f3f97, add_report_export_fields
Create Date: 2026-02-26 14:50:03.047454

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '09608b4c0b59'
down_revision: Union[str, None] = ('013e8e9f3f97', 'add_report_export_fields')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
